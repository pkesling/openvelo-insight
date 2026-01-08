from datetime import datetime
import unittest

from app.models import HourForecast


class TestModels(unittest.TestCase):
    def test_hour_forecast_creation(self):
        hf = HourForecast(
            hour_index=0,
            timestamp_utc=datetime.utcnow(),
            temperature_c=10.0,
            relative_humidity_percent=50.0,
            dewpoint_c=5.0,
            wind_speed_kmh=10.0,
            wind_direction_deg=180,
            wind_gust_kmh=12.0,
            precip_probability_percent=20.0,
            pm25_ug_m3=5.0,
            aqi=30,
            air_quality_category="Good",
        )
        self.assertEqual(hf.temperature_c, 10.0)
        self.assertEqual(hf.air_quality_category, "Good")


if __name__ == "__main__":
    unittest.main()
