"""
Central logging configuration utilities.

Usage
-----
In your entrypoint (CLI, worker, Airflow DAG, etc.):

    from myproject.logging_utils import setup_logging

    def main() -> None:
        setup_logging(level="INFO", job_name="openaq_ingest")
        ...

In a module:

    from myproject.logging_utils import get_tagged_logger

    logger = get_tagged_logger(__name__, tag="openaq_client")

    def fetch_latest() -> None:
        logger.info("Fetching latest OpenAQ data")

This ensures:
- consistent formatting across the app
- useful early logs even before setup_logging() runs
- structured fields: job_name, tag, logger name, message
"""

from __future__ import annotations

import logging
import logging.config
from typing import Any, Dict, Mapping, Optional


# ---------------------------------------------------------------------------
# Minimal bootstrap config (early logs)
# ---------------------------------------------------------------------------

# This runs on import and ensures that if any code logs *before* setup_logging()
# is called, you still get timestamps + levels instead of bare messages.
BOOTSTRAP_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
BOOTSTRAP_DATEFMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=BOOTSTRAP_FORMAT,
    datefmt=BOOTSTRAP_DATEFMT,
)


# ---------------------------------------------------------------------------
# Defaults for full configuration
# ---------------------------------------------------------------------------

DEFAULT_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(job_name)s | %(tag)s | %(name)s | %(message)s"
)
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_CONFIGURED: bool = False


# ---------------------------------------------------------------------------
# Filters to enrich log records
# ---------------------------------------------------------------------------

class MaxLevelFilter(logging.Filter):
    """
    Allow only records up to (and including) `max_level`.

    Useful to route DEBUG/INFO to stdout while WARNING+ go elsewhere.
    """

    def __init__(self, max_level: int) -> None:
        """Initialize with a maximum log level."""
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        """Return True if the record is within the allowed level."""
        return record.levelno <= self.max_level


class EnsureTagFilter(logging.Filter):
    """
    Ensure every LogRecord has a `tag` attribute.

    - If a LoggerAdapter has already provided `record.tag`, we leave it alone.
    - Otherwise we derive it from the logger name, using the last segment of
      the dotted path, e.g. "myproject.openaq.client" -> "client".
    """

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        """Ensure the record has a tag attribute."""
        if not hasattr(record, "tag"):
            # Fallback: last component of the logger name
            logger_name = getattr(record, "name", "")
            record.tag = logger_name.split(".")[-1] if logger_name else "-"
        return True


class JobNameFilter(logging.Filter):
    """
    Inject a `job_name` attribute into every LogRecord.

    Typically set once per process (e.g. the name of the ETL job, service,
    worker, or DAG). If not provided, defaults to "-".
    """

    def __init__(self, job_name: Optional[str] = None) -> None:
        """Initialize with a fixed job name."""
        super().__init__()
        self._job_name = job_name or "-"

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        """Inject the job_name attribute when missing."""
        if not hasattr(record, "job_name"):
            record.job_name = self._job_name
        return True


# ---------------------------------------------------------------------------
# Config builder and setup function
# ---------------------------------------------------------------------------


def build_logging_config(
    *,
    level: str | int = "INFO",
    log_format: str = DEFAULT_LOG_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
    job_name: Optional[str] = None,
) -> Mapping[str, Any]:
    """
    Build a dictConfig-style logging configuration.

    Parameters
    ----------
    level:
        Root logger level (e.g., "DEBUG", "INFO", logging.INFO).
    log_format:
        Formatter pattern for log messages.
    date_format:
        Formatter pattern for timestamps.
    job_name:
        Optional logical name for this process/job (e.g. "openaq_ingest").
        Used for the `job_name` field in log records.

    Returns
    -------
    dict suitable for logging.config.dictConfig().
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "ensure_tag": {"()": EnsureTagFilter},
            "job_name": {"()": JobNameFilter, "job_name": job_name},
            "stdout_max_info": {
                "()": MaxLevelFilter,
                "max_level": logging.INFO,
            },
        },
        "formatters": {
            "standard": {
                "format": log_format,
                "datefmt": date_format,
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "filters": ["ensure_tag", "job_name", "stdout_max_info"],
                "level": "DEBUG",  # lower bound
                "stream": "ext://sys.stdout",
            },
            "stderr": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "filters": ["ensure_tag", "job_name"],
                "level": "WARNING",  # WARNING and above
                "stream": "ext://sys.stderr",
            },
        },
        "root": {
            "level": level,
            "handlers": ["stdout", "stderr"],
        },
    }


def setup_logging(
    *,
    level: str | int = "INFO",
    log_format: str = DEFAULT_LOG_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
    job_name: Optional[str] = None,
    override_existing: bool = False,
) -> None:
    """
    Configure application-wide logging once per process.

    Call this from your application's entrypoint before doing real work.

    Parameters
    ----------
    level:
        Root logger level (e.g., "DEBUG", "INFO").
    log_format:
        Formatter pattern for log messages. By default includes:
            - asctime
            - levelname
            - job_name
            - tag
            - logger name
            - message
    date_format:
        Timestamp format for `asctime`.
    job_name:
        Logical name for this process/job. Appears in `%(job_name)s`.
        Useful for distinguishing multiple jobs/services sharing an infra.
    override_existing:
        If False (default), calling setup_logging() multiple times is a no-op
        after the first. If True, the configuration is reapplied each time.
    """
    global _CONFIGURED

    if _CONFIGURED and not override_existing:
        return

    config_dict = build_logging_config(
        level=level,
        log_format=log_format,
        date_format=date_format,
        job_name=job_name,
    )
    logging.config.dictConfig(config_dict)
    _CONFIGURED = True


# ---------------------------------------------------------------------------
# Logger helper
# ---------------------------------------------------------------------------


def get_tagged_logger(
    name: str,
    *,
    tag: Optional[str] = None,
) -> logging.LoggerAdapter:
    """
    Return a LoggerAdapter that always carries a `tag` field.

    Parameters
    ----------
    name:
        Base logger name (usually __name__).
    tag:
        Semantic tag for this component. If omitted, defaults to the last
        segment of the logger name, e.g. "myproject.openaq.client" -> "client".

    Returns
    -------
    logging.LoggerAdapter
        Use this just like a normal logger:

            logger = get_tagged_logger(__name__, tag="openaq_client")
            logger.info("Fetching data")

        It will emit a `tag` value for use in your formatter.
    """
    base_logger = logging.getLogger(name)
    if tag is None:
        tag = name.split(".")[-1]
    # LoggerAdapter adds the extra dict to every LogRecord
    return logging.LoggerAdapter(base_logger, {"tag": tag})


def mask_db_url(url: str) -> str:
    """Return a copy of a DB connection URL with credentials masked.

    Examples
    --------
    - postgresql://user:secret@host:5432/db -> postgresql://user:***@host:5432/db
    - sqlite:///tmp/db.sqlite -> unchanged
    """
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    # Mask query parameters that look sensitive
    masked_query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if any(token in key.lower() for token in ("pass", "pwd", "secret", "token", "key")):
            masked_query_pairs.append((key, "***"))
        else:
            masked_query_pairs.append((key, value))
    masked_query = urlencode(masked_query_pairs)

    username = "***" if parsed.username else ""
    has_password = parsed.password is not None

    netloc = ""
    if username:
        netloc += username
        if has_password:
            netloc += ":***"
        netloc += "@"

    if parsed.hostname:
        netloc += parsed.hostname
    if parsed.port:
        netloc += f":{parsed.port}"

    # Preserve triple-slash form for schemes that omit netloc (e.g., sqlite, file)
    if not netloc and parsed.netloc == "" and (parsed.path or "").startswith("/"):
        base = f"{parsed.scheme}:///{(parsed.path or '').lstrip('/')}"
        if masked_query:
            base = f"{base}?{masked_query}"
        if parsed.fragment:
            base = f"{base}#{parsed.fragment}"
        return base

    return urlunparse(
        (parsed.scheme, netloc, parsed.path or "", parsed.params or "", masked_query, parsed.fragment or "")
    )
