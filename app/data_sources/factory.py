"""Factory helpers for choosing a forecast data source at startup."""

from __future__ import annotations

from app import config
from app.data_sources.base import CallableForecastDataSource, ForecastDataSource
from app.data_sources.open_meteo_client import (
    fetch_air_current,
    fetch_air_hours,
    fetch_weather_current,
    fetch_weather_hours,
)
from utils.logging_utils import get_tagged_logger, mask_db_url

logger = get_tagged_logger(__name__, tag="data_sources/factory")


DEFAULT_SOURCE_NAME = "open_meteo"


def build_data_source(settings: config.Settings | None = None) -> ForecastDataSource:
    """Instantiate the configured forecast data source."""
    settings = settings or config.settings
    source = (settings.forecast_source or DEFAULT_SOURCE_NAME).lower()

    if source == "open_meteo":
        logger.info("Using Open-Meteo data source")
        return CallableForecastDataSource(
            weather_current=fetch_weather_current,
            air_current=fetch_air_current,
            weather_hours=fetch_weather_hours,
            air_hours=fetch_air_hours,
        )

    if source == "postgres":
        from .postgres_source import PostgresForecastDataSource

        db_url = settings.forecast_database_url
        if not db_url:
            raise ValueError("forecast_database_url must be set for Postgres data source")
        masked = mask_db_url(db_url) if db_url else db_url
        logger.info("Using Postgres data source", extra={"db_url": masked})
        return PostgresForecastDataSource.from_url(db_url)

    raise ValueError(f"Unknown forecast source '{source}'")
