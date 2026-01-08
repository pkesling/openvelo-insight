import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.forecast_service import BikeConditions, BikeHourConditions


def _make_hour(idx: int = 0) -> BikeHourConditions:
    tz = ZoneInfo("UTC")
    return BikeHourConditions(
        time=dt.datetime(2024, 1, 1, 12 + idx, 0, tzinfo=tz),
        hour_index=idx,
        temperature=20.0,
        temperature_unit="°C",
        rel_humidity=50.0,
        rel_humidity_unit="%",
        dew_point=None,
        dew_point_unit=None,
        apparent_temperature=None,
        apparent_temperature_unit=None,
        precipitation_prob=10.0,
        precipitation_prob_unit="%",
        precipitation=0.0,
        precipitation_unit="mm",
        cloud_cover=20.0,
        cloud_cover_unit="%",
        wind_speed=5.0,
        wind_speed_unit="km/h",
        wind_gusts=None,
        wind_gusts_unit=None,
        wind_direction=180.0,
        wind_direction_unit="deg",
        is_day=True,
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


def _mock_conditions():
    cur = _make_hour(0)
    forecast = [_make_hour(1)]
    return BikeConditions(current=cur, forecast=forecast)


class TestApi(unittest.TestCase):
    def setUp(self):
        import app.api as api_mod
        from app.config import settings

        self.api_mod = api_mod
        self._orig_get_bike = api_mod.get_bike_conditions_for_window
        self._orig_create_session = api_mod.create_session
        self._orig_get_session = api_mod.get_session
        self._orig_update_session = api_mod.update_session
        self._orig_narrate = api_mod.narrate_assessment
        self._orig_default_prefs = api_mod.default_preferences
        self._orig_max_len = settings.max_user_message_chars
        self._orig_api_key = settings.api_key

    def tearDown(self):
        from app.config import settings

        self.api_mod.get_bike_conditions_for_window = self._orig_get_bike
        self.api_mod.create_session = self._orig_create_session
        self.api_mod.get_session = self._orig_get_session
        self.api_mod.update_session = self._orig_update_session
        self.api_mod.narrate_assessment = self._orig_narrate
        self.api_mod.default_preferences = self._orig_default_prefs
        settings.max_user_message_chars = self._orig_max_len
        settings.api_key = self._orig_api_key
        settings.conditions_ttl_seconds = 1800

    def test_start_session_200(self):
        client = TestClient(fastapi_app)
        self.api_mod.get_bike_conditions_for_window = lambda **kwargs: _mock_conditions()
        self.api_mod.create_session = lambda messages, prefs, conditions: "abc123"

        resp = client.post("/v1/session/start")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["session_id"], "abc123")
        self.assertIsNone(data["initial_response"])
        self.assertNotEqual(data["current_conditions"]["temperature"], "")
        self.assertEqual(len(data["forecast"]), 1)

    def test_run_initial(self):
        client = TestClient(fastapi_app)
        self.api_mod.get_bike_conditions_for_window = lambda **kwargs: _mock_conditions()
        self.api_mod.create_session = lambda messages, prefs, conditions: "abc123"
        self.api_mod.update_session = lambda session_id, messages=None, preferences=None, conditions=None, assessment=None: None
        from app.agent import UserPreferences
        dummy_conditions = _mock_conditions()
        self.api_mod.get_session = lambda sid: ([], UserPreferences(), dummy_conditions, None)

        resp = client.post("/v1/session/abc123/initial")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["initial_response"])

    def test_refresh_outlook_missing_session(self):
        client = TestClient(fastapi_app)
        self.api_mod.get_session = lambda sid: None
        resp = client.post("/v1/session/unknown/refresh")
        self.assertEqual(resp.status_code, 404)

    def test_continue_chat_rejects_long_message(self):
        from app.config import settings

        client = TestClient(fastapi_app)
        settings.max_user_message_chars = 5
        self.api_mod.get_session = lambda sid: ([], None, None, None)

        resp = client.post("/v1/session/abc123/chat", json={"message": "toolong"})
        self.assertEqual(resp.status_code, 400)

    def test_start_session_requires_api_key_when_set(self):
        from app.config import settings

        client = TestClient(fastapi_app)
        settings.api_key = "sekret"
        self.api_mod.get_bike_conditions_for_window = lambda **kwargs: _mock_conditions()
        self.api_mod.create_session = lambda messages, prefs, conditions: "abc123"

        missing = client.post("/v1/session/start")
        self.assertEqual(missing.status_code, 401)

        ok = client.post("/v1/session/start", headers={"X-API-Key": "sekret"})
        self.assertEqual(ok.status_code, 200)

    def test_run_initial_fetches_when_conditions_stale(self):
        from app.config import settings
        settings.conditions_ttl_seconds = 1
        client = TestClient(fastapi_app)

        # track calls
        calls = {"fetch": 0}
        def fake_fetch(**kwargs):
            calls["fetch"] += 1
            return _mock_conditions()

        self.api_mod.get_bike_conditions_for_window = fake_fetch
        self.api_mod.update_session = lambda session_id, messages=None, preferences=None, conditions=None, assessment=None: None
        from app.agent import UserPreferences
        from app.app_types import CachedConditions
        stale = CachedConditions(
            data=_mock_conditions(),
            fetched_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2)
        )
        self.api_mod.get_session = lambda sid: ([], UserPreferences(), stale, None)

        resp = client.post("/v1/session/abc123/initial")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(calls["fetch"], 1)

    def test_start_session_invalid_timezone_400(self):
        from app.agent import UserPreferences

        client = TestClient(fastapi_app)
        self.api_mod.get_bike_conditions_for_window = lambda **kwargs: _mock_conditions()
        self.api_mod.create_session = lambda messages, prefs, conditions: "abc123"
        self.api_mod.default_preferences = lambda: UserPreferences(timezone="Not/AZone")

        resp = client.post("/v1/session/start")
        self.assertEqual(resp.status_code, 400)

    def test_continue_chat_refreshes_when_stale(self):
        from app.agent import UserPreferences
        from app.app_types import CachedConditions

        client = TestClient(fastapi_app)
        self.api_mod.get_bike_conditions_for_window = lambda **kwargs: _mock_conditions()
        prefs = UserPreferences()
        stale = CachedConditions(
            data=_mock_conditions(),
            fetched_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=3600),
        )
        self.api_mod.get_session = lambda sid: ([], prefs, stale, None)

        update_calls = {}
        def fake_update(session_id, messages=None, preferences=None, conditions=None, assessment=None):
            update_calls["conditions"] = conditions
            update_calls["assessment"] = assessment

        self.api_mod.update_session = fake_update
        self.api_mod.narrate_assessment = lambda assessment, user_message=None, prior_messages=None: (
            [{"role": "assistant", "content": "ok"}],
            "ok",
        )

        resp = client.post("/v1/session/abc123/chat", json={"message": "hi"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(update_calls.get("conditions"))
        self.assertIsNotNone(update_calls.get("assessment"))


if __name__ == "__main__":
    unittest.main()
