import unittest

from app.ollama_client import OllamaClient


class DummyResponse:
    def __init__(self, status_code=200, content="ok"):
        self.status_code = status_code
        self._content = content
        self.text = content
        # mimic requests.Response.elapsed
        self.elapsed = type("Elapsed", (), {"total_seconds": lambda self: 0.123})()

    def json(self):
        return {"message": {"content": self._content}}

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception("bad status")


class TestOllamaClient(unittest.TestCase):
    def setUp(self):
        from app import ollama_client as oc
        self._orig_post = oc.requests.post

    def tearDown(self):
        from app import ollama_client as oc
        oc.requests.post = self._orig_post

    def test_chat_success(self):
        def fake_post(url, json=None, timeout=None):
            return DummyResponse(200, "hi")

        from app import ollama_client as oc

        oc.requests.post = fake_post
        client = OllamaClient()
        out = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(out, "hi")

    def test_chat_non_200(self):
        def fake_post(url, json=None, timeout=None):
            return DummyResponse(500, "err")

        from app import ollama_client as oc

        oc.requests.post = fake_post
        client = OllamaClient()
        with self.assertRaises(RuntimeError):
            client.chat([])


if __name__ == "__main__":
    unittest.main()
