"""Thin client for calling the local Ollama chat API."""

import os
import time
import requests

from .config import settings
from utils.logging_utils import setup_logging, get_tagged_logger

setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_tagged_logger(__name__, tag="app/ollama_client")


def _base_url() -> str:
    """Return Ollama base URL without a trailing slash."""
    return str(settings.ollama_base_url).rstrip("/")


class OllamaClient:
    """Minimal client for the Ollama chat API."""
    def __init__(self):
        """Initialize client configuration from settings."""
        self.url = f"{_base_url()}/api/chat"
        self.model = settings.ollama_model
        self.options = settings.ollama_options
        self.max_retries = int(os.getenv("AGENT_OLLAMA_RETRIES", "1"))
        self.retry_backoff_sec = float(os.getenv("AGENT_OLLAMA_RETRY_BACKOFF_SEC", "0.5"))

    def chat(self, messages):
        """Send a chat request and return the assistant content."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self.options,
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                logger.debug("Ollama POST payload: %s", payload)
                r = requests.post(self.url, json=payload, timeout=180)
                logger.info(
                    "Ollama POST took %.2fs, response: %s",
                    r.elapsed.total_seconds(),
                    r.text[:200],
                )
            except requests.exceptions.RequestException as exc:
                last_error = exc
                logger.exception("Ollama POST failed on attempt %d: %s", attempt + 1, exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_sec)
                    continue
                raise

            if r.status_code == 200:
                break

            error_text = (r.text or "")[:200]
            if "EOF" in error_text and attempt < self.max_retries:
                logger.warning("Ollama returned EOF; retrying (attempt %d/%d).", attempt + 1, self.max_retries + 1)
                time.sleep(self.retry_backoff_sec)
                continue
            raise RuntimeError(
                f"Ollama POST failed with status {r.status_code}: {error_text} "
                f"(model={self.model}, url={self.url})"
            )
        else:
            if last_error is not None:
                raise RuntimeError(f"Ollama POST failed after retries: {last_error}") from last_error

        try:
            data = r.json()
        except ValueError as exc:
            raise RuntimeError(f"Ollama returned non-JSON response: {r.text[:200]}") from exc
        content = data.get("message", {}).get("content", "")
        # Normalize non-string content to string
        if isinstance(content, (dict, list)):
            content = str(content)
        return content


ollama_client = OllamaClient()
