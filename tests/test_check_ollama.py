import unittest

from app.check_ollama import get_ollama_status


class DummyResp:
    def __init__(self, json_payload, status_code=200):
        self._payload = json_payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception("bad status")

    def json(self):
        return self._payload


class TestCheckOllama(unittest.TestCase):
    def setUp(self):
        import app.check_ollama as co
        self._orig_get = co.requests.get

    def tearDown(self):
        import app.check_ollama as co
        co.requests.get = self._orig_get

    def test_get_ollama_status_ok(self):
        def fake_get(url, timeout=None):
            return DummyResp({"models": [{"name": "phi4-mini:latest"}]})

        import app.check_ollama as co

        co.requests.get = fake_get
        status = get_ollama_status(required_models=["phi4-mini"])
        self.assertTrue(status["reachable"])
        self.assertTrue(status["models_ok"])
        self.assertTrue(status["ok"])

    def test_get_ollama_status_missing(self):
        def fake_get(url, timeout=None):
            return DummyResp({"models": []})

        import app.check_ollama as co

        co.requests.get = fake_get
        status = get_ollama_status(required_models=["missing-model"])
        self.assertTrue(status["reachable"])
        self.assertFalse(status["models_ok"])
        self.assertIn("missing-model", status["missing_models"])


if __name__ == "__main__":
    unittest.main()
