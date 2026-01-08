"""Interfaces and helpers for forecast data sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Protocol

from app.data_sources.open_meteo_client import AirHour, WeatherHour


class ForecastDataSource(Protocol):
    """Interface for anything that can provide weather and air-quality data."""

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
        """Return the current weather observation."""
        ...

    def fetch_air_current(
        self,
        latitude: float,
        longitude: float,
        *,
        timezone: str = "auto",
        forecast_days: int = 5,
    ) -> AirHour:
        """Return the current air-quality observation."""
        ...

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
        """Return hourly weather observations."""
        ...

    def fetch_air_hours(
        self,
        latitude: float,
        longitude: float,
        *,
        timezone: str = "auto",
        forecast_days: int | None = None,
    ) -> List[AirHour]:
        """Return hourly air-quality observations."""
        ...


@dataclass
class CallableForecastDataSource(ForecastDataSource):
    """Wrap four callables so they can be swapped for different backends."""

    weather_current: Callable[..., WeatherHour]
    air_current: Callable[..., AirHour]
    weather_hours: Callable[..., List[WeatherHour]]
    air_hours: Callable[..., List[AirHour]]

    def fetch_weather_current(self, *args, **kwargs) -> WeatherHour:
        """Delegate to the configured current-weather callable."""
        return self.weather_current(*args, **kwargs)

    def fetch_air_current(self, *args, **kwargs) -> AirHour:
        """Delegate to the configured current air-quality callable."""
        return self.air_current(*args, **kwargs)

    def fetch_weather_hours(self, *args, **kwargs) -> List[WeatherHour]:
        """Delegate to the configured hourly-weather callable."""
        return self.weather_hours(*args, **kwargs)

    def fetch_air_hours(self, *args, **kwargs) -> List[AirHour]:
        """Delegate to the configured hourly air-quality callable."""
        return self.air_hours(*args, **kwargs)
