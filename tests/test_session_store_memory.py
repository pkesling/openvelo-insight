import time

import unittest

from app.agent import UserPreferences
from app.session_store.memory import InMemorySessionStore


class TestInMemorySessionStore(unittest.TestCase):
    def test_create_and_get_refreshes_ttl(self):
        store = InMemorySessionStore(ttl_seconds=2)
        sid = store.create_session([], UserPreferences(), None)
        self.assertIsNotNone(store.get_session(sid))
        time.sleep(1.2)
        # Access should refresh TTL; should still exist
        self.assertIsNotNone(store.get_session(sid))
        time.sleep(2.1)
        # After another sleep without access, it should expire
        self.assertIsNone(store.get_session(sid))

    def test_update_preserves_data(self):
        store = InMemorySessionStore(ttl_seconds=5)
        sid = store.create_session([], UserPreferences(), None)
        msgs, prefs, conds, _ = store.get_session(sid)
        self.assertEqual(msgs, [])
        new_msgs = [{"role": "user", "content": "hi"}]
        store.update_session(sid, messages=new_msgs)
        msgs2, prefs2, _, _ = store.get_session(sid)
        self.assertEqual(msgs2, new_msgs)
        self.assertEqual(prefs2, prefs)

    def test_max_age_expires_even_with_access(self):
        store = InMemorySessionStore(ttl_seconds=5, max_age_seconds=1)
        sid = store.create_session([], UserPreferences(), None)
        self.assertIsNotNone(store.get_session(sid))
        time.sleep(0.6)
        self.assertIsNotNone(store.get_session(sid))
        time.sleep(0.6)
        self.assertIsNone(store.get_session(sid))


if __name__ == "__main__":
    unittest.main()
