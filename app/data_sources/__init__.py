"""Data source factories for plugging different forecast backends."""

from .base import CallableForecastDataSource, ForecastDataSource
from .factory import build_data_source
from .postgres_source import PostgresForecastDataSource
from .open_meteo_client import (
    AirHour,
    WeatherHour,
    fetch_air_current,
    fetch_air_hours,
    fetch_weather_current,
    fetch_weather_hours,
)

__all__ = [
    "build_data_source",
    "PostgresForecastDataSource",
    "ForecastDataSource",
    "CallableForecastDataSource",
    "AirHour",
    "WeatherHour",
    "fetch_air_current",
    "fetch_air_hours",
    "fetch_weather_current",
    "fetch_weather_hours",
]
