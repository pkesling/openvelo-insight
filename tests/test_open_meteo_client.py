import unittest

from app.data_sources import open_meteo_client


class DummyResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _make_weather_payload():
    return {
        "current": {
            "time": "2024-01-01T12:00",
            "temperature_2m": 10.0,
            "relative_humidity_2m": 50.0,
            "apparent_temperature": 9.0,
            "is_day": 1,
            "wind_speed_10m": 5.0,
            "wind_direction_10m": 180.0,
            "wind_gusts_10m": 6.0,
            "precipitation_probability": 20.0,
            "precipitation": 0.0,
            "cloud_cover": 10.0,
        },
        "current_units": {
            "time": "iso8601",
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "apparent_temperature": "°C",
            "is_day": "boolean",
            "wind_speed_10m": "km/h",
            "wind_direction_10m": "deg",
            "wind_gusts_10m": "km/h",
            "precipitation_probability": "%",
            "precipitation": "mm",
            "cloud_cover": "%",
        },
        "hourly": {
            "time": ["2024-01-01T12:00", "2024-01-01T13:00"],
            "temperature_2m": [10.0, 11.0],
            "relative_humidity_2m": [50.0, 55.0],
            "dew_point_2m": [5.0, 6.0],
            "apparent_temperature": [9.0, 10.0],
            "precipitation_probability": [20.0, 30.0],
            "precipitation": [0.0, 0.1],
            "cloud_cover": [10.0, 20.0],
            "wind_speed_10m": [5.0, 6.0],
            "wind_gusts_10m": [6.0, 7.0],
            "wind_direction_10m": [180.0, 190.0],
            "is_day": [1, 1],
        },
        "hourly_units": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "dew_point_2m": "°C",
            "apparent_temperature": "°C",
            "precipitation_probability": "%",
            "precipitation": "mm",
            "cloud_cover": "%",
            "wind_speed_10m": "km/h",
            "wind_gusts_10m": "km/h",
            "wind_direction_10m": "deg",
            "is_day": "boolean",
        },
    }


def _make_air_payload():
    return {
        "current": {
            "time": "2024-01-01T12:00",
            "pm2_5": 5.0,
            "pm10": 10.0,
            "ozone": 30.0,
            "uv_index": 1.0,
            "us_aqi": 25,
        },
        "current_units": {
            "pm2_5": "µg/m³",
            "pm10": "µg/m³",
            "ozone": "µg/m³",
            "uv_index": "index",
            "us_aqi": "aqi",
        },
        "hourly": {
            "time": ["2024-01-01T12:00", "2024-01-01T13:00"],
            "pm2_5": [5.0, 6.0],
            "pm10": [10.0, 11.0],
            "ozone": [30.0, 31.0],
            "uv_index": [1.0, 1.1],
            "us_aqi": [25, 30],
        },
        "hourly_units": {
            "pm2_5": "µg/m³",
            "pm10": "µg/m³",
            "ozone": "µg/m³",
            "uv_index": "index",
            "us_aqi": "aqi",
        },
    }


class TestOpenMeteoClient(unittest.TestCase):
    def setUp(self):
        self._orig_session = open_meteo_client.session

    def tearDown(self):
        open_meteo_client.session = self._orig_session

    def test_fetch_weather_current(self):
        payload = _make_weather_payload()
        open_meteo_client.session = type("S", (), {"get": lambda *a, **k: DummyResp(payload)})()

        current = open_meteo_client.fetch_weather_current(0, 0)
        self.assertEqual(current.temperature, 10.0)
        self.assertEqual(current.wind_speed, 5.0)

    def test_fetch_air_current(self):
        payload = _make_air_payload()
        open_meteo_client.session = type("S", (), {"get": lambda *a, **k: DummyResp(payload)})()

        current = open_meteo_client.fetch_air_current(0, 0)
        self.assertEqual(current.pm2_5, 5.0)
        self.assertEqual(current.us_aqi, 25)

    def test_fetch_weather_hours(self):
        payload = _make_weather_payload()
        open_meteo_client.session = type("S", (), {"get": lambda *a, **k: DummyResp(payload)})()

        hours = open_meteo_client.fetch_weather_hours(0, 0)
        self.assertEqual(len(hours), 2)
        self.assertEqual(hours[1].temperature, 11.0)

    def test_fetch_air_hours(self):
        payload = _make_air_payload()
        open_meteo_client.session = type("S", (), {"get": lambda *a, **k: DummyResp(payload)})()

        hours = open_meteo_client.fetch_air_hours(0, 0)
        self.assertEqual(len(hours), 2)
        self.assertEqual(hours[0].us_aqi, 25)


if __name__ == "__main__":
    unittest.main()
