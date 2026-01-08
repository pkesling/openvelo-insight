import unittest

from app.main import app, _STATIC_DIR


class TestMain(unittest.TestCase):
    def test_app_metadata(self):
        self.assertEqual(app.title, "Biking Conditions Agent")
        self.assertTrue(_STATIC_DIR.exists())


if __name__ == "__main__":
    unittest.main()
