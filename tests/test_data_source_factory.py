import types
import unittest

from app.data_sources.factory import build_data_source, DEFAULT_SOURCE_NAME
import app.data_sources.factory as factory
from app.data_sources.base import CallableForecastDataSource


class DummySettings:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        # provide defaults if not passed
        self.forecast_source = getattr(self, "forecast_source", DEFAULT_SOURCE_NAME)
        self.forecast_database_url = getattr(self, "forecast_database_url", None)


class TestDataSourceFactory(unittest.TestCase):
    def test_build_open_meteo_default(self):
        settings = DummySettings(forecast_source="open_meteo")
        ds = build_data_source(settings)
        self.assertIsInstance(ds, CallableForecastDataSource)

    def test_unknown_source_raises(self):
        settings = DummySettings(forecast_source="unknown-source")
        with self.assertRaises(ValueError):
            build_data_source(settings)

    def test_postgres_branch_uses_from_url(self):
        sentinel = object()
        settings = DummySettings(forecast_source="postgres", forecast_database_url="postgresql://u:p@h/db")
        # Import inside test to avoid missing attribute if not imported at module scope
        from app.data_sources import postgres_source as pg_module
        orig_class = pg_module.PostgresForecastDataSource
        try:
            pg_module.PostgresForecastDataSource = types.SimpleNamespace(from_url=lambda url: sentinel)
            ds = build_data_source(settings)
            self.assertIs(ds, sentinel)
        finally:
            pg_module.PostgresForecastDataSource = orig_class

    def test_postgres_missing_url_raises(self):
        settings = DummySettings(forecast_source="postgres", forecast_database_url=None)
        with self.assertRaises(ValueError):
            build_data_source(settings)


if __name__ == "__main__":
    unittest.main()
