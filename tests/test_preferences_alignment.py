import unittest

from app.agent import UserPreferences
from app.domain import RiderPreferences


class TestPreferencesAlignment(unittest.TestCase):
    """Tests to ensure the user preferences and rider preferences models are aligned."""
    def test_user_and_rider_preferences_fields_match(self):
        self.assertEqual(
            set(UserPreferences.model_fields.keys()),
            set(RiderPreferences.model_fields.keys()),
        )

    def test_user_preferences_roundtrip_to_rider_preferences(self):
        prefs = UserPreferences()
        rider_prefs = RiderPreferences(**prefs.model_dump())
        self.assertIsInstance(rider_prefs, RiderPreferences)


if __name__ == "__main__":
    unittest.main()
