"""Thin client for calling the local Ollama chat API."""

import os
import requests

from .config import settings
from utils.logging_utils import setup_logging, get_tagged_logger

setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_tagged_logger(__name__, tag="ollama_client")


def _base_url() -> str:
    """Return Ollama base URL without trailing slash."""
    return str(settings.ollama_base_url).rstrip("/")


class OllamaClient:
    """Minimal client for the Ollama chat API."""
    def __init__(self):
        """Initialize client configuration from settings."""
        self.url = f"{_base_url()}/api/chat"
        self.model = settings.ollama_model
        self.options = settings.ollama_options

    def chat(self, messages):
        """Send a chat request and return the assistant content."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self.options,
        }

        try:
            logger.debug("Ollama POST payload: %s", payload)
            r = requests.post(self.url, json=payload, timeout=180)
            logger.info(f"Ollama POST took {r.elapsed.total_seconds():.2f}s, response: {r.text[:200]}")
        except requests.exceptions.RequestException as exc:
            logger.exception(f"Ollama POST failed: {exc}")
            raise

        if r.status_code != 200:
            raise RuntimeError(f"Ollama POST failed with status {r.status_code}: {r.text[:200]}")

        data = r.json()
        content = data.get("message", {}).get("content", "")
        # Normalize non-string content to string
        if isinstance(content, (dict, list)):
            content = str(content)
        return content


ollama_client = OllamaClient()
