"""Postgres-backed forecast data source.

Defaults now point at the `stg.open_meteo_weather` and `stg.open_meteo_air`
tables produced by the event-driven-open-weather-insight project. Column names
may follow either our earlier normalized schema (e.g., temperature) or
Open-Meteo's raw naming (e.g., temperature_2m); both are supported.
"""

from __future__ import annotations

import datetime as dt
from typing import List, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.data_sources.base import ForecastDataSource
from app.data_sources.open_meteo_client import AirHour, WeatherHour
from utils.logging_utils import get_tagged_logger

logger = get_tagged_logger(__name__, tag="postgres_data_source")


class PostgresForecastDataSource(ForecastDataSource):
    """Fetch forecasts from Postgres instead of Open-Meteo."""

    DEFAULT_TIMEZONE = "UTC"

    def __init__(
        self,
        engine: Engine,
        *,
        current_weather_table: str = "mart.fct_open_meteo_current_weather_air_conditions",
        forecast_weather_table: str = "mart.fct_open_meteo_latest_weather_air_forecast",
        current_air_table: str = "mart.fct_open_meteo_current_weather_air_conditions",
        forecast_air_table: str = "mart.fct_open_meteo_latest_weather_air_forecast",
    ) -> None:
        """Bind to a database engine and optionally override source tables."""
        self.engine = engine
        self.current_weather_table = current_weather_table
        self.current_air_table = current_air_table
        self.forecast_weather_table = forecast_weather_table
        self.forecast_air_table = forecast_air_table

    @classmethod
    def from_url(cls, database_url: str, **kwargs) -> "PostgresForecastDataSource":
        """Create an engine from a URL and build the data source."""
        engine = create_engine(database_url, future=True)
        return cls(engine, **kwargs)

    @classmethod
    def _resolve_timezone(cls, tz_name: str | None) -> str:
        """Resolve sentinel/default timezone names to a real tz."""
        if not tz_name or tz_name == "auto":
            return cls.DEFAULT_TIMEZONE
        return tz_name

    @classmethod
    def _normalize_timezone(cls, tz_name: str | None) -> str:
        """Return a timezone name valid for both SQL and Python, falling back to UTC."""
        resolved = cls._resolve_timezone(tz_name)
        try:
            ZoneInfo(resolved)
            return resolved
        except Exception:
            logger.warning("Invalid timezone; falling back to UTC", extra={"tz_name": tz_name})
            return cls.DEFAULT_TIMEZONE

    @classmethod
    def _localize(cls, ts: dt.datetime, tz_name: str) -> dt.datetime:
        """Return a timezone-aware timestamp, falling back to UTC on errors."""
        resolved_tz = cls._normalize_timezone(tz_name)
        tzinfo = ZoneInfo(resolved_tz)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return ts.astimezone(tzinfo)

    @staticmethod
    def _get_value(row: Mapping, *keys):
        """Return the first non-null value for the provided keys."""
        for key in keys:
            if key in row and row[key] is not None:
                return row[key]
        return None

    @staticmethod
    def _convert_temperature(
        value: float | None, unit: str | None, target_unit: str | None
    ) -> tuple[float | None, str | None]:
        """Convert temperature to a requested unit, preserving unknown units."""
        src = (unit or "").lower()
        target = (target_unit or "").lower()
        if value is None:
            if target in {"fahrenheit", "f", "°f"}:
                return None, "°F"
            if target in {"celsius", "c", "°c"}:
                return None, "°C"
            return None, target_unit or unit
        if target in {"fahrenheit", "f", "°f"}:
            if src.startswith("c"):
                return (value * 9 / 5) + 32, "°F"
            return value, unit or "°F"
        if target in {"celsius", "c", "°c"}:
            if src.startswith("f"):
                return (value - 32) * 5 / 9, "°C"
            return value, unit or "°C"
        return value, unit

    @staticmethod
    def _convert_wind_speed(
        value: float | None, unit: str | None, target_unit: str | None
    ) -> tuple[float | None, str | None]:
        """Convert wind speed to a requested unit, preserving unknown units."""
        src = (unit or "").lower()
        target = (target_unit or "").lower()
        if value is None:
            if target in {"mph", "mi/h"}:
                return None, "mph"
            if target in {"km/h", "kph"}:
                return None, "km/h"
            if target in {"m/s", "ms^-1", "mps"}:
                return None, "m/s"
            return None, target_unit or unit
        if target in {"mph", "mi/h"}:
            if src in {"km/h", "kph"}:
                return value * 0.621371, "mph"
            if src in {"m/s", "ms^-1", "mps"}:
                return value * 2.23694, "mph"
            return value, unit or "mph"
        if target in {"km/h", "kph"}:
            if src in {"mph", "mi/h"}:
                return value / 0.621371, "km/h"
            if src in {"m/s", "ms^-1", "mps"}:
                return value * 3.6, "km/h"
            return value, unit or "km/h"
        if target in {"m/s", "ms^-1", "mps"}:
            if src in {"mph", "mi/h"}:
                return value / 2.23694, "m/s"
            if src in {"km/h", "kph"}:
                return value / 3.6, "m/s"
            return value, unit or "m/s"
        return value, unit

    @staticmethod
    def _convert_precipitation(
        value: float | None, unit: str | None, target_unit: str | None
    ) -> tuple[float | None, str | None]:
        """Convert precipitation depth to a requested unit."""
        src = (unit or "").lower()
        target = (target_unit or "").lower()
        if value is None:
            if target in {"inch", "in"}:
                return None, "inch"
            if target in {"mm", "millimeter", "millimetre"}:
                return None, "mm"
            return None, target_unit or unit
        if target in {"inch", "in"}:
            if src in {"mm", "millimeter", "millimetre"}:
                return value / 25.4, "inch"
            return value, unit or "inch"
        if target in {"mm", "millimeter", "millimetre"}:
            if src in {"inch", "in"}:
                return value * 25.4, "mm"
            return value, unit or "mm"
        return value, unit

    def _row_to_weather(
        self,
        row: Mapping,
        tz_name: str,
        idx: int | None = None,
        *,
        temperature_unit: str = "fahrenheit",
        wind_speed_unit: str = "mph",
        precipitation_unit: str = "mm",
    ) -> WeatherHour:
        """Map a weather row from Postgres into a WeatherHour."""
        temp, temp_unit = self._convert_temperature(
            self._get_value(row, "temperature", "temperature_2m"),
            self._get_value(row, "temperature_unit", "temperature_2m_unit"),
            temperature_unit,
        )
        dew_point, dew_point_unit = self._convert_temperature(
            self._get_value(row, "dew_point", "dew_point_2m"),
            self._get_value(row, "dew_point_unit", "dew_point_2m_unit"),
            temperature_unit,
        )
        apparent, apparent_unit = self._convert_temperature(
            self._get_value(row, "apparent_temperature"),
            self._get_value(row, "apparent_temperature_unit"),
            temperature_unit,
        )
        wind_speed, wind_speed_unit_out = self._convert_wind_speed(
            self._get_value(row, "wind_speed", "wind_speed_10m"),
            self._get_value(row, "wind_speed_unit", "wind_speed_10m_unit"),
            wind_speed_unit,
        )
        wind_gusts, wind_gusts_unit_out = self._convert_wind_speed(
            self._get_value(row, "wind_gusts", "wind_gusts_10m"),
            self._get_value(row, "wind_gusts_unit", "wind_gusts_10m_unit"),
            wind_speed_unit,
        )
        precipitation, precipitation_unit_out = self._convert_precipitation(
            self._get_value(row, "precipitation"),
            self._get_value(row, "precipitation_unit"),
            precipitation_unit,
        )

        return WeatherHour(
            time=self._localize(row["open_meteo_start_time"], tz_name),
            hour_index=row.get("hour_index", idx or 0),
            temperature=temp,
            temperature_unit=temp_unit or "°F",
            rel_humidity=self._get_value(row, "relative_humidity", "relative_humidity_2m"),
            rel_humidity_unit=self._get_value(row, "relative_humidity_unit", "relative_humidity_2m_unit"),
            dew_point=dew_point,
            dew_point_unit=dew_point_unit or temp_unit,
            apparent_temperature=apparent,
            apparent_temperature_unit=apparent_unit or temp_unit,
            precipitation_prob=self._get_value(row, "precipitation_prob", "precipitation_probability"),
            precipitation_prob_unit=self._get_value(row, "precipitation_prob_unit", "precipitation_probability_unit"),
            precipitation=precipitation,
            precipitation_unit=precipitation_unit_out,
            cloud_cover=self._get_value(row, "cloud_cover"),
            cloud_cover_unit=self._get_value(row, "cloud_cover_unit"),
            wind_speed=wind_speed,
            wind_speed_unit=wind_speed_unit_out or wind_speed_unit,
            wind_gusts=wind_gusts,
            wind_gusts_unit=wind_gusts_unit_out or wind_speed_unit,
            wind_direction=self._get_value(row, "wind_direction", "wind_direction_10m"),
            wind_direction_unit=self._get_value(row, "wind_direction_unit", "wind_direction_10m_unit"),
            is_day=self._get_value(row, "is_day"),
        )

    def _row_to_air(self, row: Mapping, tz_name: str) -> AirHour:
        """Map an air-quality row from Postgres into an AirHour."""
        return AirHour(
            time=self._localize(row["open_meteo_start_time"], tz_name),
            pm2_5=self._get_value(row, "pm2_5"),
            pm2_5_unit=self._get_value(row, "pm2_5_unit"),
            pm10=self._get_value(row, "pm10"),
            pm10_unit=self._get_value(row, "pm10_unit"),
            us_aqi=self._get_value(row, "us_aqi"),
            us_aqi_unit=self._get_value(row, "us_aqi_unit"),
            ozone=self._get_value(row, "ozone"),
            ozone_unit=self._get_value(row, "ozone_unit"),
            uv_index=self._get_value(row, "uv_index"),
            uv_index_unit=self._get_value(row, "uv_index_unit"),
        )

    def fetch_weather_current(
        self,
        latitude: float,
        longitude: float,
        *,
        timezone: str = "auto",
        temperature_unit: str = "fahrenheit",
        wind_speed_unit: str = "mph",
        precipitation_unit: str = "mm",
    ) -> WeatherHour:
        """Fetch the latest weather record for a location."""
        tz_name = self._normalize_timezone(timezone)
        query = text(
            f"""
            SELECT weather_event_id,
                   open_meteo_start_time,
                   open_meteo_end_time,
                   latitude,
                   longitude,
                   temperature,
                   temperature_unit,
                   rel_humidity,
                   rel_humidity_unit,
                   dew_point,
                   dew_point_unit,
                   apparent_temperature,
                   apparent_temperature_unit,
                   precipitation_prob,
                   precipitation_prob_unit,
                   precipitation,
                   precipitation_unit,
                   cloud_cover,
                   cloud_cover_unit,
                   wind_speed,
                   wind_speed_unit,
                   wind_gusts,
                   wind_gusts_unit,
                   wind_direction,
                   wind_direction_unit,
                   is_day
              FROM {self.current_weather_table}
             WHERE latitude = :lat AND longitude = :lon
             ORDER BY open_meteo_start_time DESC
             LIMIT 1
            """
        )
        logger.debug(f"Executing query for location ({latitude},{longitude}): {query}")
        with self.engine.connect() as conn:
            row = conn.execute(query, {"lat": latitude, "lon": longitude}).mappings().first()
        if not row:
            raise LookupError("No weather data found")
        return self._row_to_weather(
            row,
            tz_name,
            temperature_unit=temperature_unit,
            wind_speed_unit=wind_speed_unit,
            precipitation_unit=precipitation_unit,
        )

    def fetch_air_current(
        self,
        latitude: float,
        longitude: float,
        *,
        timezone: str = "auto",
        forecast_days: int = 5,
    ) -> AirHour:
        """Fetch the latest air-quality record for a location."""
        tz_name = self._normalize_timezone(timezone)
        query = text(
            f"""
            SELECT air_event_id,
                   open_meteo_start_time,
                   open_meteo_end_time,
                   latitude,
                   longitude,
                   pm2_5,
                   pm2_5_unit,
                   pm10,
                   pm10_unit,
                   us_aqi,
                   us_aqi_unit,
                   ozone,
                   ozone_unit,
                   uv_index,
                   uv_index_unit
              FROM {self.current_air_table}
             WHERE latitude = :lat AND longitude = :lon
             ORDER BY open_meteo_start_time DESC
             LIMIT 1
            """
        )
        logger.debug(f"Executing query for location ({latitude},{longitude}): {query}")
        with self.engine.connect() as conn:
            row = conn.execute(query, {"lat": latitude, "lon": longitude}).mappings().first()
        if not row:
            raise LookupError("No air quality data found")
        return self._row_to_air(row, tz_name)

    def fetch_weather_hours(
        self,
        latitude: float,
        longitude: float,
        *,
        timezone: str = "auto",
        forecast_days: int | None = None,
        temperature_unit: str = "fahrenheit",
        wind_speed_unit: str = "mph",
        precipitation_unit: str = "mm",
    ) -> List[WeatherHour]:
        """Fetch an hourly weather forecast for the requested number of days."""
        tz_name = self._normalize_timezone(timezone)
        days = forecast_days or 7
        query = text(
            f"""
            SELECT weather_event_id,
                   open_meteo_start_time,
                   open_meteo_end_time,
                   latitude,
                   longitude,
                   temperature,
                   temperature_unit,
                   rel_humidity,
                   rel_humidity_unit,
                   dew_point,
                   dew_point_unit,
                   apparent_temperature,
                   apparent_temperature_unit,
                   precipitation_prob,
                   precipitation_prob_unit,
                   precipitation,
                   precipitation_unit,
                   cloud_cover,
                   cloud_cover_unit,
                   wind_speed,
                   wind_speed_unit,
                   wind_gusts,
                   wind_gusts_unit,
                   wind_direction,
                   wind_direction_unit,
                   is_day
              FROM {self.forecast_weather_table}
             WHERE latitude = :lat AND longitude = :lon
               AND open_meteo_start_time >= timezone(:tz, now())
               AND open_meteo_start_time < timezone(:tz, now()) + make_interval(days => :days)
             ORDER BY open_meteo_start_time               
            """
        )
        logger.debug(f"Executing query for location ({latitude},{longitude}): {query}")
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"lat": latitude, "lon": longitude, "days": days, "tz": tz_name}).mappings().all()
        return [
            self._row_to_weather(
                row,
                tz_name,
                idx=i,
                temperature_unit=temperature_unit,
                wind_speed_unit=wind_speed_unit,
                precipitation_unit=precipitation_unit,
            )
            for i, row in enumerate(rows)
        ]

    def fetch_air_hours(
        self,
        latitude: float,
        longitude: float,
        *,
        timezone: str = "auto",
        forecast_days: int | None = None,
    ) -> List[AirHour]:
        """Fetch an hourly air-quality forecast for the requested number of days."""
        tz_name = self._normalize_timezone(timezone)
        days = forecast_days or 5
        query = text(
            f"""
            SELECT air_event_id,
                   open_meteo_start_time,
                   open_meteo_end_time,
                   latitude,
                   longitude,
                   pm2_5,
                   pm2_5_unit,
                   pm10,
                   pm10_unit,
                   us_aqi,
                   us_aqi_unit,
                   ozone,
                   ozone_unit,
                   uv_index,
                   uv_index_unit
              FROM {self.forecast_air_table}            
             WHERE latitude = :lat AND longitude = :lon
               AND open_meteo_start_time >= timezone(:tz, now())
               AND open_meteo_start_time < timezone(:tz, now()) + make_interval(days => :days)
             ORDER BY open_meteo_start_time
            """
        )
        logger.debug(f"Executing query for location ({latitude},{longitude}): {query}")
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"lat": latitude, "lon": longitude, "days": days, "tz": tz_name}).mappings().all()
        return [self._row_to_air(row, tz_name) for row in rows]
