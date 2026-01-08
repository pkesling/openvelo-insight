# app/check_ollama.py
"""Health checks and optional auto-pulling for required Ollama models."""

import os
import sys
from typing import Iterable, Optional, Dict, Any

import requests

from utils.logging_utils import setup_logging, get_tagged_logger

setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_tagged_logger(__name__, tag="check_ollama")

# Default from environment: AGENT_AUTO_PULL_OLLAMA_MODELS=true|false
_AUTO_PULL_DEFAULT = os.getenv("AGENT_AUTO_PULL_OLLAMA_MODELS", "true").lower() in (
    "1",
    "true",
    "yes",
)


def _base_url() -> str:
    """Return the configured Ollama base URL without a trailing slash."""
    return os.getenv("AGENT_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def _tags_url() -> str:
    """Return the Ollama tags endpoint URL."""
    return f"{_base_url()}/api/tags"


def _pull_url() -> str:
    """Return the Ollama pull endpoint URL."""
    return f"{_base_url()}/api/pull"


def _installed_model_names(tags_json: dict) -> set[str]:
    """Extract model names (including base names) from tags JSON."""
    models = tags_json.get("models", [])
    names: set[str] = set()
    for m in models:
        name = m.get("name")
        if not name:
            continue
        names.add(name)
        # Also include the base name without a tag so callers can require either form.
        base = name.split(":")[0]
        names.add(base)
    return names


def get_ollama_status(required_models: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """
    Non-fatal probe of Ollama.

    Returns a dict like:
    {
      "ok": bool,
      "reachable": bool,
      "base_url": "...",
      "installed_models": [...],
      "required_models": [...],
      "missing_models": [...],
      "models_ok": bool,
      "error": "...",   # present if something went wrong
    }

    This NEVER sys.exit(). Suitable for health checks.
    """
    required_models = list(required_models or [])
    status: Dict[str, Any] = {
        "ok": False,
        "reachable": False,
        "base_url": _base_url(),
        "installed_models": [],
        "required_models": required_models,
        "missing_models": [],
        "models_ok": False,
        "error": None,
    }

    try:
        resp = requests.get(_tags_url(), timeout=3)
        # some test doubles may not expose .text; fall back gracefully
        body_text = getattr(resp, "text", "<no-body>")
        logger.debug(f"Ollama tags response: {body_text}")
        resp.raise_for_status()
    except Exception as e:
        status["error"] = str(e)
        # ok/reachable/models_ok all remain False
        return status

    status["reachable"] = True
    tags = resp.json()
    installed = _installed_model_names(tags)
    status["installed_models"] = sorted(installed)

    if required_models:
        missing = [m for m in required_models if m not in installed]
        status["missing_models"] = missing
        status["models_ok"] = len(missing) == 0
    else:
        status["models_ok"] = True

    status["ok"] = status["reachable"] and status["models_ok"]
    return status


def _pull_model(name: str) -> None:
    """
    Ask Ollama to pull a model by name via /api/pull.

    This will block until the pull finishes or fails.
    """
    logger.info(f"⏳ Model '{name}' not found; requesting Ollama to pull it...")

    try:
        with requests.post(_pull_url(), json={"name": name}, stream=True, timeout=None) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    msg = line.decode("utf-8")
                except Exception:
                    continue
                if '"status"' in msg:
                    logger.info(f"   [ollama] {msg}")
    except Exception as e:
        logger.exception(f"\nERROR: Failed to pull Ollama model '{name}'.\n"
                         f"   Details: {e}\n"
                         f"   Try pulling manually inside your Ollama environment:\n"
                         f"     ollama pull {name}")
        sys.exit(1)

    # Verify it really exists now
    status = get_ollama_status(required_models=[name])
    if not status.get("models_ok"):
        logger.error(f"\nERROR: Model '{name}' still not visible after pull.\n"
                     f"   Ollama may be in an unhealthy state.")
        logger.debug(f"   Ollama status: {status}")
        sys.exit(1)

    logger.info(f"Model '{name}' is now available.")


def check_ollama(
    required_models: Optional[Iterable[str]] = None,
    auto_pull: Optional[bool] = None,
) -> None:
    """
    "Hard" check for startup.

    - Fails with sys.exit(1) if Ollama isn't reachable or required models are missing
      and auto_pull is disabled / fails.
    - If auto_pull=True (default from AUTO_PULL_OLLAMA_MODELS), tries to pull missing models.
    """
    if auto_pull is None:
        auto_pull = _AUTO_PULL_DEFAULT

    required_models = list(required_models or [])
    if not required_models:
        # Nothing specifically required; just make sure Ollama is up.
        required_models = []

    status = get_ollama_status(required_models=required_models)

    if not status["reachable"]:
        logger.error(f"\nERROR: Ollama does not appear to be running or is unreachable.\n"
                     f"   Tried: {_tags_url()}")
        if status["error"]:
            logger.error(f"   Details: {status['error']}")
        logger.error("\n   Make sure Ollama is installed and running.\n"
                     "   Example:\n"
                     "     • Install: https://ollama.com/download\n"
                     "     • Start:  ollama serve (or your Dockerized Ollama service)")
        sys.exit(1)

    missing = status["missing_models"]

    if not missing:
        logger.info(f"Ollama reachable at {_base_url()}")
        if required_models:
            logger.info(f"Required models available: {', '.join(required_models)}")
        else:
            logger.info(f"Ollama has installed models: {', '.join(status['installed_models'])}")
        return

    # We have missing models.
    if auto_pull:
        for name in missing:
            _pull_model(name)
        return

    # No auto-pull; fail with a helpful message.
    logger.error("\nERROR: Required Ollama models are not installed:")
    for m in missing:
        logger.error(f"   • {m}")
    logger.error("\nInstall them using:")
    for m in missing:
        logger.error(f"   ollama pull {m}")

    sys.exit(1)
