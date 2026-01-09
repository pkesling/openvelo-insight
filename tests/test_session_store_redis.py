import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from app.agent import UserPreferences
from app.app_types import CachedAssessment, CachedConditions
from app.domain import AgentAssessmentPayload, AssessmentContext, RiderPreferences
from app.forecast_service import BikeConditions, BikeHourConditions
from app.session_store.redis import RedisSessionStore


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.expires = {}

    def setex(self, key, ttl, value):
        self.store[key] = value
        self.expires[key] = ttl

    def get(self, key):
        return self.store.get(key)

    def expire(self, key, ttl):
        self.expires[key] = ttl

    def delete(self, key):
        self.store.pop(key, None)
        self.expires.pop(key, None)

    def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        return [k for k in list(self.store.keys()) if k.startswith(prefix)]


class TestRedisSessionStore(unittest.TestCase):
    def _sample_conditions(self):
        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(hours=1)
        hour1 = BikeHourConditions(
            time=t1,
            hour_index=0,
            temperature=70.0,
            temperature_unit="°F",
            rel_humidity=50.0,
            rel_humidity_unit="%",
            dew_point=55.0,
            dew_point_unit="°F",
            apparent_temperature=69.0,
            apparent_temperature_unit="°F",
            precipitation_prob=10.0,
            precipitation_prob_unit="%",
            precipitation=0.0,
            precipitation_unit="mm",
            cloud_cover=20.0,
            cloud_cover_unit="%",
            wind_speed=5.0,
            wind_speed_unit="mph",
            wind_gusts=8.0,
            wind_gusts_unit="mph",
            wind_direction=180.0,
            wind_direction_unit="°",
            is_day=True,
            pm2_5=5.0,
            pm2_5_unit="µg/m³",
            pm10=8.0,
            pm10_unit="µg/m³",
            us_aqi=20,
            us_aqi_unit="USAQI",
            ozone=40.0,
            ozone_unit="µg/m³",
            uv_index=3.0,
            uv_index_unit="",
        )
        hour2 = BikeHourConditions(
            time=t2,
            hour_index=1,
            temperature=68.0,
            temperature_unit="°F",
            rel_humidity=52.0,
            rel_humidity_unit="%",
            dew_point=54.0,
            dew_point_unit="°F",
            apparent_temperature=67.0,
            apparent_temperature_unit="°F",
            precipitation_prob=5.0,
            precipitation_prob_unit="%",
            precipitation=0.0,
            precipitation_unit="mm",
            cloud_cover=25.0,
            cloud_cover_unit="%",
            wind_speed=6.0,
            wind_speed_unit="mph",
            wind_gusts=9.0,
            wind_gusts_unit="mph",
            wind_direction=190.0,
            wind_direction_unit="°",
            is_day=True,
            pm2_5=6.0,
            pm2_5_unit="µg/m³",
            pm10=9.0,
            pm10_unit="µg/m³",
            us_aqi=22,
            us_aqi_unit="USAQI",
            ozone=42.0,
            ozone_unit="µg/m³",
            uv_index=3.5,
            uv_index_unit="",
        )
        return CachedConditions(
            data=BikeConditions(current=hour1, forecast=[hour2]),
            fetched_at=t1,
        )

    def _sample_assessment(self):
        context = AssessmentContext(latitude=1.0, longitude=2.0, timezone="UTC", generated_at=datetime.now(timezone.utc))
        prefs = RiderPreferences(latitude=1.0, longitude=2.0, timezone="UTC")
        payload = AgentAssessmentPayload(context=context, preferences=prefs)
        return CachedAssessment(data=payload, generated_at=context.generated_at)

    def test_create_get_update_delete_round_trip(self):
        client = FakeRedis()
        store = RedisSessionStore(client, ttl_seconds=10, prefix="session:")

        conditions = self._sample_conditions()
        assessment = self._sample_assessment()
        sid = store.create_session([], UserPreferences(), conditions, assessment)
        key = f"session:{sid}"
        self.assertIn(key, client.store)

        fetched = store.get_session(sid)
        self.assertIsNotNone(fetched)
        msgs, prefs, conds, assess = fetched
        self.assertEqual(msgs, [])
        self.assertIsInstance(prefs, UserPreferences)
        self.assertIsInstance(conds, CachedConditions)
        self.assertEqual(len(conds.data.forecast), 1)
        self.assertEqual(conds.data.current.temperature, 70.0)
        self.assertEqual(conds.data.forecast[0].temperature, 68.0)
        self.assertIsInstance(assess, CachedAssessment)
        self.assertEqual(assess.data.preferences.latitude, 1.0)
        # expire should have been refreshed
        self.assertEqual(client.expires[key], 10)

        new_msgs = [{"role": "user", "content": "hi"}]
        store.update_session(sid, messages=new_msgs)
        fetched2 = store.get_session(sid)
        self.assertEqual(fetched2[0], new_msgs)

        store.delete_session(sid)
        self.assertIsNone(store.get_session(sid))

    def test_clear_removes_prefixed_keys(self):
        client = FakeRedis()
        store = RedisSessionStore(client, ttl_seconds=10, prefix="session:")
        other_key = "session:other"
        client.store[other_key] = b"junk"

        sid = store.create_session([], UserPreferences(), None)
        store.clear()

        self.assertEqual(client.store, {})
        self.assertEqual(client.expires, {})

    def test_get_session_handles_corrupt_data(self):
        client = FakeRedis()
        store = RedisSessionStore(client, ttl_seconds=10, prefix="session:")
        sid = "bad"
        client.store[f"session:{sid}"] = b"not-json"
        self.assertIsNone(store.get_session(sid))

    def test_max_age_caps_refresh_and_expires(self):
        client = FakeRedis()
        store = RedisSessionStore(client, ttl_seconds=10, max_age_seconds=15, prefix="session:")

        with patch("app.session_store.redis.time.time") as mock_time:
            mock_time.return_value = 1000.0
            sid = store.create_session([], UserPreferences(), None)
            key = f"session:{sid}"
            self.assertEqual(client.expires[key], 10)

            mock_time.return_value = 1005.0
            self.assertIsNotNone(store.get_session(sid))
            self.assertEqual(client.expires[key], 10)

            mock_time.return_value = 1014.0
            self.assertIsNotNone(store.get_session(sid))
            self.assertEqual(client.expires[key], 1)

            mock_time.return_value = 1016.0
            self.assertIsNone(store.get_session(sid))
            self.assertNotIn(key, client.store)


if __name__ == "__main__":
    unittest.main()
