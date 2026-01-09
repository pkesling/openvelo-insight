"""Merge weather and air quality data into bike-friendly conditions."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import math
from typing import List, Optional, Dict, Union

from app.data_sources import CallableForecastDataSource, ForecastDataSource
from app.data_sources.open_meteo_client import (
    AirHour,
    WeatherHour,
    fetch_air_current,
    fetch_air_hours,
    fetch_weather_current,
    fetch_weather_hours,
)
from utils.logging_utils import get_tagged_logger
logger = get_tagged_logger(__name__, tag="app/forecast_service")
# TODO: incorporate NWS alerts/discussions into conditions payload for hazard-aware scoring.


@dataclass
class BikeConditions:
    """Bundle of current and forecast bike conditions."""
    current: BikeHourConditions
    forecast: List[BikeHourConditions]


@dataclass
class BikeHourConditions:
    """Merged weather/air-quality conditions for a single hour."""
    time: dt.datetime  # timezone-aware
    hour_index: int
    temperature: float
    temperature_unit: str
    rel_humidity: Optional[float]
    rel_humidity_unit: Optional[str]
    dew_point: Optional[float]
    dew_point_unit: Optional[str]
    apparent_temperature: Optional[float]
    apparent_temperature_unit: Optional[str]
    precipitation_prob: Optional[float]
    precipitation_prob_unit: Optional[str]
    precipitation: Optional[float]
    precipitation_unit: Optional[str]
    cloud_cover: Optional[float]
    cloud_cover_unit: Optional[str]
    wind_speed: Optional[float]
    wind_speed_unit: Optional[str]
    wind_gusts: Optional[float]
    wind_gusts_unit: Optional[str]
    wind_direction: Optional[float]
    wind_direction_unit: Optional[str]
    is_day: Optional[bool]
    pm2_5: Optional[float]
    pm2_5_unit: Optional[str]
    pm10: Optional[float]
    pm10_unit: Optional[str]
    us_aqi: Optional[int]
    us_aqi_unit: Optional[str]
    ozone: Optional[float]
    ozone_unit: Optional[str]
    uv_index: Optional[float]
    uv_index_unit: Optional[str]
    # future fields: comfort_score, air_quality_band, etc.

    @staticmethod
    def _fmt(val, unit, fmt: str) -> str:
        """Format a value/unit pair or return an empty string."""
        if val is None or unit is None:
            return ""
        try:
            return f"{fmt.format(val)} {unit}"
        except Exception:
            return ""

    def to_display_strings(self) -> Union[dict | None]:
        """Return a display-friendly dict for API serialization."""
        try:
            return {
                "timestamp_utc": self.time.isoformat(),
                "temperature": self._fmt(self.temperature, self.temperature_unit, "{:.1f}"),
                "relative_humidity": self._fmt(self.rel_humidity, self.rel_humidity_unit, "{:.0f}"),
                "dew_point": self._fmt(self.dew_point, self.dew_point_unit, "{:.1f}"),
                "apparent_temperature": self._fmt(self.apparent_temperature, self.apparent_temperature_unit, "{:.1f}"),
                "precipitation_prob": self._fmt(self.precipitation_prob, self.precipitation_prob_unit, "{:.0f}"),
                "precipitation": self._fmt(self.precipitation, self.precipitation_unit, "{:.0f}"),
                "cloud_cover": self._fmt(self.cloud_cover, self.cloud_cover_unit, "{:.0f}"),
                "wind_speed": self._fmt(self.wind_speed, self.wind_speed_unit, "{:.1f}"),
                "wind_gusts": self._fmt(self.wind_gusts, self.wind_gusts_unit, "{:.1f}"),
                "wind_direction": self._fmt(self.wind_direction, self.wind_direction_unit, "{:.0f}"),
                "is_day": "true" if self.is_day is True else "false" if self.is_day is False else "",
                "pm2_5": self._fmt(self.pm2_5, self.pm2_5_unit, "{:.0f}"),
                "pm10": self._fmt(self.pm10, self.pm10_unit, "{:.0f}"),
                "us_aqi": self._fmt(self.us_aqi, self.us_aqi_unit, "{:.0f}"),
                "ozone": self._fmt(self.ozone, self.ozone_unit, "{:.0f}"),
                "uv_index": self._fmt(self.uv_index, self.uv_index_unit, "{:.0f}"),
            }
        except Exception as e:
            logger.error(
                "Error converting BikeHourConditions to display strings: %s",
                e,
            )
            return None


def _normalize_is_day(value: Optional[object]) -> Optional[bool]:
    """Normalize Open-Meteo is_day values (0/1, bool, string) into bool or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "t", "yes", "y"}:
            return True
        if lowered in {"0", "false", "f", "no", "n"}:
            return False
    logger.debug("Unrecognized is_day value; treating as unknown", extra={"is_day": value})
    return None


def _index_air_by_time(air: List[AirHour]) -> Dict[dt.datetime, AirHour]:
    """Index air-quality hours by timestamp."""
    return {a.time: a for a in air}


def generate_bike_conditions(weather: WeatherHour, air: AirHour) -> BikeHourConditions:
    """Merge weather and air observations into a BikeHourConditions object."""
    return BikeHourConditions(
        time=weather.time,
        hour_index=weather.hour_index,
        temperature=weather.temperature,
        temperature_unit=weather.temperature_unit,
        rel_humidity=weather.rel_humidity,
        rel_humidity_unit=weather.rel_humidity_unit,
        dew_point=weather.dew_point,
        dew_point_unit=weather.dew_point_unit,
        apparent_temperature=weather.apparent_temperature,
        apparent_temperature_unit=weather.apparent_temperature_unit,
        precipitation_prob=weather.precipitation_prob,
        precipitation_prob_unit=weather.precipitation_prob_unit,
        precipitation=weather.precipitation,
        precipitation_unit=weather.precipitation_unit,
        cloud_cover=weather.cloud_cover,
        cloud_cover_unit=weather.cloud_cover_unit,
        wind_speed=weather.wind_speed,
        wind_speed_unit=weather.wind_speed_unit,
        wind_gusts=weather.wind_gusts,
        wind_gusts_unit=weather.wind_gusts_unit,
        wind_direction=weather.wind_direction,
        wind_direction_unit=weather.wind_direction_unit,
        is_day=_normalize_is_day(weather.is_day),
        pm2_5=air.pm2_5 if air else None,
        pm2_5_unit=air.pm2_5_unit if air else None,
        pm10=air.pm10 if air else None,
        pm10_unit=air.pm10_unit if air else None,
        us_aqi=air.us_aqi if air else None,
        us_aqi_unit=air.us_aqi_unit if air else None,
        ozone=air.ozone if air else None,
        ozone_unit=air.ozone_unit if air else None,
        uv_index=air.uv_index if air else None,
        uv_index_unit=air.uv_index_unit if air else None,
    )


def get_bike_conditions_for_window(
    latitude: float,
    longitude: float,
    start_local: dt.datetime,
    end_local: dt.datetime,
    *,
    timezone: str = "auto",
    forecast_hours: int | None = None,
    forecast_days: int | None = None,
    data_source: ForecastDataSource | None = None,
) -> BikeConditions:
    """
    Fetch merged weather + air-quality conditions for all hours in [start_local, end_local).

    Assumes start/end are timezone-aware datetimes in the same timezone that Open-Meteo
    returns (controlled by the `timezone` param). The `data_source` argument lets you
    inject alternate providers (database, different API, cached layer, etc.).
    """
    days = forecast_days
    # Resolve days from forecast_hours or the requested window span.
    if days is None:
        hours = forecast_hours if forecast_hours is not None else 24
        days_by_hours = max(1, math.ceil(hours / 24))
        try:
            day_span = (end_local.date() - start_local.date()).days
            days_by_window = max(1, day_span + 1)
        except Exception:
            days_by_window = 1
        days = max(days_by_hours, days_by_window)
        logger.debug(
            "Resolved forecast_days from window/hours",
            extra={
                "days_by_hours": days_by_hours,
                "days_by_window": days_by_window,
                "forecast_days": days,
            },
        )

    logger.info(
        "Fetching bike conditions for window",
        extra={
            "latitude": latitude,
            "longitude": longitude,
            "start_local": start_local.isoformat(),
            "end_local": end_local.isoformat(),
            "timezone": timezone,
        },
    )

    ds = data_source or CallableForecastDataSource(
        fetch_weather_current,
        fetch_air_current,
        fetch_weather_hours,
        fetch_air_hours,
    )

    current_weather = ds.fetch_weather_current(latitude, longitude, timezone=timezone)
    current_air = ds.fetch_air_current(latitude, longitude, timezone=timezone)
    logger.debug("Fetched current weather and air")
    current_conditions = generate_bike_conditions(current_weather, current_air)

    hourly_weather = ds.fetch_weather_hours(latitude, longitude, timezone=timezone, forecast_days=days or 7)
    hourly_air = ds.fetch_air_hours(latitude, longitude, timezone=timezone, forecast_days=days or 7)
    logger.debug("Fetched weather and air hours")

    air_index = _index_air_by_time(hourly_air)

    forecast: List[BikeHourConditions] = []
    hour_idx: int = 0
    for w in hourly_weather:
        if not (start_local <= w.time < end_local):
            continue

        a = air_index.get(w.time)

        forecast.append(
            generate_bike_conditions(w, a)
        )
        hour_idx += 1

    logger.info(
        "Computed bike conditions for window",
        extra={"conditions_count": len(forecast)},
    )

    bike_conditions = BikeConditions(current=current_conditions,
                                     forecast=forecast)

    return bike_conditions


def main():
    """Manual test helper for forecast aggregation."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    lat, lon = 43.07, -89.40
    tz = "America/Chicago"
    tzinfo = ZoneInfo(tz)

    start = dt.datetime(2025, 12, 1, 7, 0, tzinfo=tzinfo)
    end = dt.datetime(2025, 12, 1, 10, 0, tzinfo=tzinfo)

    hours = get_bike_conditions_for_window(lat, lon, start, end, timezone=tz)
    for h in hours.forecast:
        print(f"forecast time: {h.time}\n"
              f"    temp: {h.temperature} {h.temperature_unit}\n"
              f"    relative humidity: {h.rel_humidity} {h.rel_humidity_unit}\n"
              f"    dew point: {h.dew_point} {h.dew_point_unit}\n"
              f"    apparent temperature: {h.apparent_temperature} {h.apparent_temperature_unit}\n"
              f"    precipitation prob: {h.precipitation_prob} {h.precipitation_prob_unit}\n"
              f"    cloud cover: {h.cloud_cover} {h.cloud_cover_unit}\n"
              f"    wind speed: {h.wind_speed} {h.wind_speed_unit}\n"
              f"    wind gusts: {h.wind_gusts} {h.wind_gusts_unit}\n"
              f"    wind direction: {h.wind_direction} {h.wind_direction_unit}\n"
              f"    is daylight: {h.is_day}\n"
              f"    aqi: {h.us_aqi} {h.us_aqi_unit}\n"
              f"    ozone: {h.ozone} {h.ozone_unit}\n"
              f"    uv index: {h.uv_index} {h.uv_index_unit}\n")


if __name__ == "__main__":
    main()
