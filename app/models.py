"""Legacy/unused Pydantic models for hourly forecasts (kept for compatibility)."""

from pydantic import BaseModel
from datetime import datetime


class HourForecast(BaseModel):
    """Compatibility schema for hourly forecast records."""
    hour_index: int
    timestamp_utc: datetime

    temperature_c: float
    relative_humidity_percent: float | None = None
    dewpoint_c: float | None = None

    wind_speed_kmh: float
    wind_direction_deg: int | None = None
    wind_gust_kmh: float | None = None

    precip_probability_percent: float

    pm25_ug_m3: float | None = None
    aqi: int | None = None
    air_quality_category: str | None = None
    air_quality_discussion: str | None = None

    short_description: str | None = None
    detailed_description: str | None = None
