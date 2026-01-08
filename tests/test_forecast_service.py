import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from app.forecast_service import get_bike_conditions_for_window
from app.data_sources import CallableForecastDataSource
from app.data_sources.open_meteo_client import WeatherHour, AirHour


class TestForecastService(unittest.TestCase):
    def test_forecast_days_spans_midnight(self):
        tz = ZoneInfo("America/Chicago")
        start_local = dt.datetime(2025, 1, 1, 22, 0, tzinfo=tz)
        end_local = start_local + dt.timedelta(hours=4)  # crosses midnight

        calls = {"weather_days": None, "air_days": None}

        def fake_weather_current(*_args, **_kwargs):
            return WeatherHour(
                time=start_local,
                hour_index=0,
                temperature=32.0,
                temperature_unit="°F",
                rel_humidity=50.0,
                rel_humidity_unit="%",
                dew_point=20.0,
                dew_point_unit="°F",
                apparent_temperature=30.0,
                apparent_temperature_unit="°F",
                precipitation_prob=0.0,
                precipitation_prob_unit="%",
                precipitation=0.0,
                precipitation_unit="mm",
                cloud_cover=10.0,
                cloud_cover_unit="%",
                wind_speed=5.0,
                wind_speed_unit="mph",
                wind_gusts=8.0,
                wind_gusts_unit="mph",
                wind_direction=180.0,
                wind_direction_unit="°",
                is_day=False,
            )

        def fake_air_current(*_args, **_kwargs):
            return AirHour(
                time=start_local,
                pm2_5=None,
                pm2_5_unit=None,
                pm10=None,
                pm10_unit=None,
                us_aqi=None,
                us_aqi_unit=None,
                ozone=None,
                ozone_unit=None,
                uv_index=None,
                uv_index_unit=None,
            )

        def fake_weather_hours(*_args, **kwargs):
            calls["weather_days"] = kwargs.get("forecast_days")
            return [
                WeatherHour(
                    time=start_local + dt.timedelta(hours=1),
                    hour_index=1,
                    temperature=30.0,
                    temperature_unit="°F",
                    rel_humidity=55.0,
                    rel_humidity_unit="%",
                    dew_point=18.0,
                    dew_point_unit="°F",
                    apparent_temperature=28.0,
                    apparent_temperature_unit="°F",
                    precipitation_prob=5.0,
                    precipitation_prob_unit="%",
                    precipitation=0.0,
                    precipitation_unit="mm",
                    cloud_cover=20.0,
                    cloud_cover_unit="%",
                    wind_speed=6.0,
                    wind_speed_unit="mph",
                    wind_gusts=10.0,
                    wind_gusts_unit="mph",
                    wind_direction=190.0,
                    wind_direction_unit="°",
                    is_day=False,
                ),
                WeatherHour(
                    time=start_local + dt.timedelta(hours=2),
                    hour_index=2,
                    temperature=29.0,
                    temperature_unit="°F",
                    rel_humidity=60.0,
                    rel_humidity_unit="%",
                    dew_point=17.0,
                    dew_point_unit="°F",
                    apparent_temperature=27.0,
                    apparent_temperature_unit="°F",
                    precipitation_prob=10.0,
                    precipitation_prob_unit="%",
                    precipitation=0.0,
                    precipitation_unit="mm",
                    cloud_cover=25.0,
                    cloud_cover_unit="%",
                    wind_speed=7.0,
                    wind_speed_unit="mph",
                    wind_gusts=11.0,
                    wind_gusts_unit="mph",
                    wind_direction=200.0,
                    wind_direction_unit="°",
                    is_day=False,
                ),
            ]

        def fake_air_hours(*_args, **kwargs):
            calls["air_days"] = kwargs.get("forecast_days")
            return [
                AirHour(
                    time=start_local + dt.timedelta(hours=1),
                    pm2_5=None,
                    pm2_5_unit=None,
                    pm10=None,
                    pm10_unit=None,
                    us_aqi=None,
                    us_aqi_unit=None,
                    ozone=None,
                    ozone_unit=None,
                    uv_index=None,
                    uv_index_unit=None,
                ),
                AirHour(
                    time=start_local + dt.timedelta(hours=2),
                    pm2_5=None,
                    pm2_5_unit=None,
                    pm10=None,
                    pm10_unit=None,
                    us_aqi=None,
                    us_aqi_unit=None,
                    ozone=None,
                    ozone_unit=None,
                    uv_index=None,
                    uv_index_unit=None,
                ),
            ]

        ds = CallableForecastDataSource(
            fake_weather_current,
            fake_air_current,
            fake_weather_hours,
            fake_air_hours,
        )

        get_bike_conditions_for_window(
            latitude=43.0,
            longitude=-89.0,
            start_local=start_local,
            end_local=end_local,
            timezone="America/Chicago",
            forecast_hours=4,
            data_source=ds,
        )

        self.assertIsNotNone(calls["weather_days"])
        self.assertIsNotNone(calls["air_days"])
        self.assertGreaterEqual(calls["weather_days"], 2)
        self.assertGreaterEqual(calls["air_days"], 2)


if __name__ == "__main__":
    unittest.main()
