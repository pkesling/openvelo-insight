"""Session manager facade over pluggable backends."""
from datetime import datetime, timezone
from typing import Optional

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    redis = None

from app.agent import UserPreferences
from app.config import settings
from app.session_store import InMemorySessionStore, RedisSessionStore, SessionStore
from app.app_types import CachedAssessment, CachedConditions
from app.domain import AgentAssessmentPayload
from utils.logging_utils import get_tagged_logger

logger = get_tagged_logger(__name__, tag="session_manager")


def _init_store() -> SessionStore:
    """Initialize the backing session store based on configuration."""
    logger.debug(f"Initializing session store: redis_url='{settings.session_redis_url or 'None'}', redis package present: {'yes' if redis else 'no'}")
    if settings.session_redis_url and redis:
        try:
            client = redis.Redis.from_url(settings.session_redis_url)
            client.ping()
            logger.info("Using RedisSessionStore", extra={"redis_url": settings.session_redis_url})
            return RedisSessionStore(client, ttl_seconds=settings.session_ttl_seconds)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Falling back to InMemorySessionStore (Redis unavailable)", extra={"error": str(exc)})
    return InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)


_store: SessionStore = _init_store()


def use_in_memory_store_for_tests(ttl_seconds: int = 3600) -> None:
    """Override store for tests to ensure isolation and determinism."""
    global _store
    _store = InMemorySessionStore(ttl_seconds=ttl_seconds)


def _wrap_assessment(assessment):
    """Wrap assessment payloads with metadata for storage."""
    if assessment is None or isinstance(assessment, CachedAssessment):
        return assessment
    if isinstance(assessment, AgentAssessmentPayload):
        return CachedAssessment(data=assessment, generated_at=datetime.now(timezone.utc))
    return assessment


def _unwrap_assessment(assessment):
    """Unwrap stored assessment payloads to their original type."""
    if isinstance(assessment, CachedAssessment):
        return assessment.data
    return assessment


def create_session(
    messages,
    preferences: Optional[UserPreferences] = None,
    conditions: Optional[CachedConditions] = None,
    assessment=None,
) -> str:
    """Create and persist a new session payload, returning its ID."""
    return _store.create_session(messages, preferences, conditions, _wrap_assessment(assessment))


def get_session(session_id: str):
    """Fetch a session payload by ID, refreshing TTL if applicable."""
    payload = _store.get_session(session_id)
    if payload and len(payload) == 3:
        messages, preferences, conditions = payload
        return messages, preferences, conditions, None
    if payload and len(payload) == 4:
        messages, preferences, conditions, assessment = payload
        return messages, preferences, conditions, _unwrap_assessment(assessment)
    return payload


def update_session(
    session_id: str,
    messages=None,
    preferences: Optional[UserPreferences] = None,
    conditions: Optional[CachedConditions] = None,
    assessment=None,
):
    """Update parts of a stored session (messages/preferences/conditions)."""
    return _store.update_session(session_id, messages, preferences, conditions, _wrap_assessment(assessment))


def delete_session(session_id: str):
    """Delete a session by ID."""
    return _store.delete_session(session_id)


def clear_sessions():
    """Clear all sessions from the backing store (dev/testing)."""
    return _store.clear()
