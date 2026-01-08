import os

import uvicorn

from app.check_ollama import check_ollama
from utils.logging_utils import get_tagged_logger

logger = get_tagged_logger(__name__, tag="server")


def maybe_check_ollama() -> None:
    """
    Optionally run the Ollama preflight. Controlled by:
    - AGENT_SKIP_OLLAMA_CHECK=true to skip entirely (useful in dev/tests)
    - AGENT_OLLAMA_MODEL to pick the required model name.
    """
    if os.getenv("AGENT_SKIP_OLLAMA_CHECK", "false").lower() in ("1", "true", "yes"):
        logger.info("Skipping Ollama preflight (AGENT_SKIP_OLLAMA_CHECK=true)")
        return

    required = [os.getenv("AGENT_OLLAMA_MODEL", "phi4-mini")]
    try:
        check_ollama(required_models=required, auto_pull=None)
    except SystemExit:
        # Allow caller to see the exit, but log a clear message first.
        logger.error("Ollama preflight failed; set AGENT_SKIP_OLLAMA_CHECK=true to bypass during dev/tests.")
        raise


if __name__ == "__main__":
    maybe_check_ollama()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False,
    )
