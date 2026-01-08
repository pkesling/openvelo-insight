"""Helpers for fetching weather and air-quality data from the Open-Meteo APIs."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional
from zoneinfo import ZoneInfo
import requests

from utils.logging_utils import get_tagged_logger
logger = get_tagged_logger(__name__, tag='open_meteo_client')

try:
    import requests_cache
    from retry_requests import retry
    logger.info("Using requests_cache and retry_requests")
except ImportError:
    logger.warning("Failed to import requests_cache and retry_requests.  Proceeding without caching.")
    requests_cache = None
    retry = None

if requests_cache and retry:
    cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
    session = retry(cache_session, retries=5, backoff_factor=0.2)
else:
    session = requests.Session()

OPEN_METEO_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

EXPECTED_WEATHER_UNITS = {
    "temperature_2m": "°F",
    "relative_humidity_2m": "%",
    "apparent_temperature": "°F",
    "precipitation_probability": "%",
    "precipitation": "mm",
    "cloud_cover": "%",
    "wind_speed_10m": "mph",
    "wind_gusts_10m": "mph",
    "wind_direction_10m": "°",
    "dew_point_2m": "°F",
}

EXPECTED_AIR_UNITS = {
    "pm2_5": "µg/m³",
    "pm10": "µg/m³",
    "us_aqi": "USAQI",
    "ozone": "µg/m³",
    "uv_index": "",  # often empty string from API
}

# Acceptable alternative units that should not trigger warnings (API/localized differences).
ALLOWED_WEATHER_UNIT_SYNONYMS = {
    "temperature_2m": {"°C", "°F"},
    "relative_humidity_2m": {"%", "percent"},
    "apparent_temperature": {"°C", "°F"},
    "precipitation_probability": {"%", "percent"},
    "precipitation": {"mm", "inch"},
    "cloud_cover": {"%", "percent"},
    "wind_speed_10m": {"mph", "km/h"},
    "wind_gusts_10m": {"mph", "km/h"},
    "wind_direction_10m": {"°", "deg", "degrees"},
    "dew_point_2m": {"°C", "°F"},
}

ALLOWED_AIR_UNIT_SYNONYMS = {
    "pm2_5": {"µg/m³", "ug/m3"},
    "pm10": {"µg/m³", "ug/m3"},
    "us_aqi": {"USAQI", "aqi", "US AQI"},
    "ozone": {"µg/m³", "ug/m3"},
    "uv_index": {"", "index", "UV-index"},
}


@dataclass
class WeatherHour:
    """Normalized hourly weather reading returned by Open-Meteo."""
    time: dt.datetime  # timezone-aware
    hour_index: int
    temperature: float
    temperature_unit:str
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


@dataclass
class AirHour:
    """Normalized hourly air-quality reading returned by Open-Meteo."""
    time: dt.datetime  # timezone-aware
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


def _iso_to_dt_with_tz(s: str, tz_name: str) -> dt.datetime:
    """Interpret Open-Meteo local time string as being in tz_name."""
    naive = dt.datetime.fromisoformat(s)
    # Treat the given timestamp as local time in tz_name
    return naive.replace(tzinfo=ZoneInfo(tz_name))


def _warn_on_unexpected_units(units: dict, *, context: str):
    """Log a warning if Open-Meteo returns units we did not request/expect."""
    if not units:
        return
    for field, expected in EXPECTED_WEATHER_UNITS.items():
        if field not in units:
            continue
        actual = units.get(field)
        if actual and actual != expected:
            allowed = ALLOWED_WEATHER_UNIT_SYNONYMS.get(field, set())
            if actual not in allowed:
                logger.warning(
                    "Unexpected Open-Meteo unit",
                    extra={"context": context, "field": field, "unit": actual, "expected": expected, "allowed": sorted(allowed)},
                )


def _warn_on_unexpected_air_units(units: dict, *, context: str):
    """Log a warning if Open-Meteo returns unexpected air-quality units."""
    if not units:
        return
    for field, expected in EXPECTED_AIR_UNITS.items():
        if field not in units:
            continue
        actual = units.get(field)
        if actual is None:
            continue
        if expected == "" and actual == "":
            continue
        if actual != expected:
            allowed = ALLOWED_AIR_UNIT_SYNONYMS.get(field, set())
            if actual not in allowed:
                logger.warning(
                    "Unexpected Open-Meteo air unit",
                    extra={"context": context, "field": field, "unit": actual, "expected": expected, "allowed": sorted(allowed)},
                )


def fetch_weather_current(latitude: float,
                          longitude: float,
                          *,
                          timezone: str = "America/Chicago",
                          temperature_unit: str = "fahrenheit",
                          wind_speed_unit: str = "mph",
                          precipitation_unit: str = "mm",
                         ) -> WeatherHour:
    """Fetch the latest available weather observation for the given coordinates."""
    current_vars = ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "is_day", "wind_speed_10m",
                    "wind_direction_10m", "wind_gusts_10m", "precipitation", "cloud_cover"]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join(current_vars),
        "timezone": timezone,
        "temperature_unit": temperature_unit,
        "wind_speed_unit": wind_speed_unit,
        "precipitation_unit": precipitation_unit,
    }

    resp = session.get(OPEN_METEO_WEATHER_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    current = data["current"]
    current_units = data["current_units"]
    _warn_on_unexpected_units(current_units, context="weather_current")
    time = current["time"]
    temp = current["temperature_2m"]
    temp_unit = current_units["temperature_2m"]
    rel_humidity = current.get("relative_humidity_2m", None)
    rel_humidity_unit = current_units.get("relative_humidity_2m", None)
    dew_point = current.get("dew_point_2m", None)
    dew_point_unit = current_units.get("dew_point_2m", None)
    apparent = current.get("apparent_temperature", None)
    apparent_unit = current_units.get("apparent_temperature", None)
    precip_prob = current.get("precipitation_probability", None)
    precip_prob_unit = current_units.get("precipitation_probability", None)
    precip = current.get("precipitation", None)
    precip_unit = current_units.get("precipitation", None)
    cloud = current.get("cloud_cover", None)
    cloud_unit = current_units.get("cloud_cover", None)
    wind_speed = current.get("wind_speed_10m", None)
    wind_speed_unit = current_units.get("wind_speed_10m", None)
    wind_gusts = current.get("wind_gusts_10m", None)
    wind_gusts_unit = current_units.get("wind_gusts_10m", None)
    wind_dir = current.get("wind_direction_10m", None)
    wind_dir_unit = current_units.get("wind_direction_10m", None)
    is_day = current.get("is_day", None)

    current_weather = WeatherHour(
        time=_iso_to_dt_with_tz(time, timezone),
        hour_index=0,
        temperature=temp,
        temperature_unit=temp_unit,
        rel_humidity=rel_humidity,
        rel_humidity_unit=rel_humidity_unit,
        dew_point=dew_point,
        dew_point_unit=dew_point_unit,
        apparent_temperature=apparent,
        apparent_temperature_unit=apparent_unit,
        precipitation_prob=precip_prob,
        precipitation_prob_unit=precip_prob_unit,
        precipitation=precip,
        precipitation_unit=precip_unit,
        cloud_cover=cloud,
        cloud_cover_unit=cloud_unit,
        wind_speed=wind_speed,
        wind_speed_unit=wind_speed_unit,
        wind_gusts=wind_gusts,
        wind_gusts_unit=wind_gusts_unit,
        wind_direction=wind_dir,
        wind_direction_unit=wind_dir_unit,
        is_day=is_day,
    )

    return current_weather


def fetch_weather_hours(
    latitude: float,
    longitude: float,
    *,
    timezone: str = "America/Chicago",
    forecast_days: int = 7,
    temperature_unit: str = "fahrenheit",
    wind_speed_unit: str = "mph",
    precipitation_unit: str = "mm",
) -> List[WeatherHour]:
    """Fetch up to `forecast_days` of hourly weather and return as structured objects."""
    hourly_vars = [
        "temperature_2m",
        "relative_humidity_2m",
        "dew_point_2m",
        "apparent_temperature",
        "precipitation_probability",
        "precipitation",
        "cloud_cover",
        "wind_speed_10m",
        "wind_gusts_10m",
        "wind_direction_10m",
        "is_day",
    ]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(hourly_vars),
        "forecast_days": forecast_days,
        "timezone": timezone,
        "temperature_unit": temperature_unit,
        "wind_speed_unit": wind_speed_unit,
        "precipitation_unit": precipitation_unit,
    }

    resp = session.get(OPEN_METEO_WEATHER_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    hourly = data["hourly"]
    hourly_units = data["hourly_units"]
    _warn_on_unexpected_units(hourly_units, context="weather_hourly")
    times = hourly["time"]
    temp = hourly["temperature_2m"]
    temp_unit = hourly_units["temperature_2m"]
    rel_humidity = hourly.get("relative_humidity_2m", [None] * len(times))
    rel_humidity_unit = hourly_units.get("relative_humidity_2m", None)
    dew_point = hourly.get("dew_point_2m", [None] * len(times))
    dew_point_unit = hourly_units.get("dew_point_2m", None)
    apparent = hourly.get("apparent_temperature", [None] * len(times))
    apparent_unit = hourly_units.get("apparent_temperature", None)
    precip_prob = hourly.get("precipitation_probability", [None] * len(times))
    precip_prob_unit = hourly_units.get("precipitation_probability", None)
    precip = hourly.get("precipitation", [None] * len(times))
    precip_unit = hourly_units.get("precipitation", None)
    cloud = hourly.get("cloud_cover", [None] * len(times))
    cloud_unit = hourly_units.get("cloud_cover", None)
    wind_speed = hourly.get("wind_speed_10m", [None] * len(times))
    wind_speed_unit = hourly_units.get("wind_speed_10m", None)
    wind_gusts = hourly.get("wind_gusts_10m", [None] * len(times))
    wind_gusts_unit = hourly_units.get("wind_gusts_10m", None)
    wind_dir = hourly.get("wind_direction_10m", [None] * len(times))
    wind_dir_unit = hourly_units.get("wind_direction_10m", None)
    is_day = hourly.get("is_day", [None] * len(times))

    out: List[WeatherHour] = []
    for i, t in enumerate(times):
        out.append(
            WeatherHour(
                time=_iso_to_dt_with_tz(t, timezone),
                hour_index=i,
                temperature=temp[i],
                temperature_unit=temp_unit,
                rel_humidity=rel_humidity[i],
                rel_humidity_unit=rel_humidity_unit,
                dew_point=dew_point[i],
                dew_point_unit=dew_point_unit,
                apparent_temperature=apparent[i],
                apparent_temperature_unit=apparent_unit,
                precipitation_prob=precip_prob[i],
                precipitation_prob_unit=precip_prob_unit,
                precipitation=precip[i],
                precipitation_unit=precip_unit,
                cloud_cover=cloud[i],
                cloud_cover_unit=cloud_unit,
                wind_speed=wind_speed[i],
                wind_speed_unit=wind_speed_unit,
                wind_gusts=wind_gusts[i],
                wind_gusts_unit=wind_gusts_unit,
                wind_direction=wind_dir[i],
                wind_direction_unit=wind_dir_unit,
                is_day=is_day[i],
            )
        )
    return out


def fetch_air_current(
    latitude: float,
    longitude: float,
    *,
    timezone: str = "America/Chicago",
    forecast_days: int = 5,
) ->AirHour:
    """Fetch the latest air-quality observation for the given coordinates."""
    current_vars = [
        "pm2_5",
        "pm10",
        "ozone",
        "uv_index",
        "us_aqi",
    ]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join(current_vars),
        "forecast_days": forecast_days,
        "timezone": timezone,
    }

    resp = session.get(OPEN_METEO_AIR_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    current = data["current"]
    current_units = data["current_units"]
    _warn_on_unexpected_air_units(current_units, context="air_current")
    time = current["time"]
    pm25 = current.get("pm2_5", None)
    pm25_unit = current_units.get("pm2_5", None)
    pm10 = current.get("pm10", None)
    pm10_unit = current_units.get("pm10", None)
    ozone = current.get("ozone", None)
    ozone_unit = current_units.get("ozone", None)
    uv = current.get("uv_index", None)
    uv_unit = current_units.get("uv_index", None)
    us_aqi = current.get("us_aqi", None)
    us_aqi_unit = current_units.get("us_aqi", None)

    current_air = AirHour(
        time=_iso_to_dt_with_tz(time, timezone),
        pm2_5=pm25,
        pm2_5_unit=pm25_unit,
        pm10=pm10,
        pm10_unit=pm10_unit,
        ozone=ozone,
        ozone_unit=ozone_unit,
        uv_index=uv,
        uv_index_unit=uv_unit,
        us_aqi=us_aqi,
        us_aqi_unit=us_aqi_unit,
    )

    return current_air


def fetch_air_hours(
    latitude: float,
    longitude: float,
    *,
    timezone: str = "America/Chicago",
    forecast_days: int = 5,
) -> List[AirHour]:
    """Fetch up to 5 days of hourly air quality forecast."""
    hourly_vars = [
        "pm2_5",
        "pm10",
        "ozone",
        "uv_index",
        "us_aqi",
    ]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(hourly_vars),
        "forecast_days": forecast_days,
        "timezone": timezone,
    }

    resp = session.get(OPEN_METEO_AIR_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    hourly = data["hourly"]
    hourly_units = data["hourly_units"]
    _warn_on_unexpected_air_units(hourly_units, context="air_hourly")
    times = hourly["time"]
    pm25 = hourly.get("pm2_5", [None] * len(times))
    pm25_unit = hourly_units.get("pm2_5", None)
    pm10 = hourly.get("pm10", [None] * len(times))
    pm10_unit = hourly_units.get("pm10", None)
    ozone = hourly.get("ozone", [None] * len(times))
    ozone_unit = hourly_units.get("ozone", None)
    uv = hourly.get("uv_index", [None] * len(times))
    uv_unit = hourly_units.get("uv_index", None)
    us_aqi = hourly.get("us_aqi", [None] * len(times))
    us_aqi_unit = hourly_units.get("us_aqi", None)

    out: List[AirHour] = []
    for i, t in enumerate(times):
        out.append(
            AirHour(
                time=_iso_to_dt_with_tz(t, timezone),
                pm2_5=pm25[i],
                pm2_5_unit=pm25_unit,
                pm10=pm10[i],
                pm10_unit=pm10_unit,
                ozone=ozone[i],
                ozone_unit=ozone_unit,
                uv_index=uv[i],
                uv_index_unit=uv_unit,
                us_aqi=us_aqi[i],
                us_aqi_unit=us_aqi_unit,
            )
        )
    return out
