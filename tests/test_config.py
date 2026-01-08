import os
import unittest

from app.config import Settings


class TestConfig(unittest.TestCase):
    def test_settings_defaults(self):
        previous = os.environ.pop("AGENT_OLLAMA_BASE_URL", None)
        try:
            s = Settings()
            self.assertEqual(s.ollama_base_url, "http://localhost:11434")
            self.assertEqual(s.forecast_days, 7)
        finally:
            if previous is not None:
                os.environ["AGENT_OLLAMA_BASE_URL"] = previous

    def test_settings_env_override(self):
        previous = os.environ.get("AGENT_OLLAMA_BASE_URL")
        try:
            os.environ["AGENT_OLLAMA_BASE_URL"] = "http://example.com"
            s = Settings()
            self.assertEqual(str(s.ollama_base_url), "http://example.com")
        finally:
            if previous is None:
                os.environ.pop("AGENT_OLLAMA_BASE_URL", None)
            else:
                os.environ["AGENT_OLLAMA_BASE_URL"] = previous

    def test_forecast_days_override(self):
        previous = os.environ.get("AGENT_FORECAST_DAYS")
        try:
            os.environ["AGENT_FORECAST_DAYS"] = "3"
            s = Settings()
            self.assertEqual(s.forecast_days, 3)
        finally:
            if previous is None:
                os.environ.pop("AGENT_FORECAST_DAYS", None)
            else:
                os.environ["AGENT_FORECAST_DAYS"] = previous


if __name__ == "__main__":
    unittest.main()
