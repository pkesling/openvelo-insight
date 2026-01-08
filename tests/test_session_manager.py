import unittest

from app import session_manager
from app.agent import UserPreferences
from app.app_types import CachedAssessment, CachedConditions
from app.domain import AgentAssessmentPayload, AssessmentContext, RiderPreferences
from datetime import datetime, timezone


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        session_manager.use_in_memory_store_for_tests()
        session_manager.clear_sessions()

    def test_session_lifecycle(self):
        prefs = UserPreferences()
        messages = [{"role": "assistant", "content": "hello"}]

        fake_conditions = CachedConditions(data=None, fetched_at=datetime.now(timezone.utc))  # type: ignore[arg-type]
        sid = session_manager.create_session(messages, prefs, fake_conditions)
        fetched_messages, fetched_prefs, fetched_conditions, _assessment = session_manager.get_session(sid)

        self.assertEqual(fetched_messages, messages)
        self.assertEqual(fetched_prefs, prefs)
        self.assertEqual(fetched_conditions, fake_conditions)

        new_messages = messages + [{"role": "user", "content": "hi"}]
        session_manager.update_session(sid, messages=new_messages)
        updated_messages, _, updated_conditions, _ = session_manager.get_session(sid)
        self.assertEqual(updated_messages, new_messages)
        self.assertEqual(updated_conditions, fake_conditions)

    def test_session_expires_after_ttl(self):
        session_manager.use_in_memory_store_for_tests(ttl_seconds=1)
        session_manager.clear_sessions()
        sid = session_manager.create_session([], UserPreferences(), None)
        self.assertIsNotNone(session_manager.get_session(sid))
        import time as _time
        _time.sleep(1.1)
        self.assertIsNone(session_manager.get_session(sid))

    def test_get_session_normalizes_legacy_payload(self):
        sid = session_manager.create_session([], UserPreferences(), None)
        store = session_manager._store
        orig_get = store.get_session
        try:
            store.get_session = lambda session_id: ([], UserPreferences(), None)
            payload = session_manager.get_session(sid)
            self.assertEqual(len(payload), 4)
            _messages, _prefs, _conditions, assessment = payload
            self.assertIsNone(assessment)
        finally:
            store.get_session = orig_get

    def test_get_session_unwraps_cached_assessment(self):
        payload = AgentAssessmentPayload(context=AssessmentContext(), preferences=RiderPreferences())
        wrapped = CachedAssessment(data=payload, generated_at=datetime.now(timezone.utc))
        sid = session_manager.create_session([], UserPreferences(), None, assessment=wrapped)
        _messages, _prefs, _conditions, assessment = session_manager.get_session(sid)
        self.assertIsInstance(assessment, AgentAssessmentPayload)


if __name__ == "__main__":
    unittest.main()
