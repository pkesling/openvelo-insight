"""In-memory session store with TTL, intended for development and tests."""

import threading
import time
import uuid
from typing import Any, Optional

from app.agent import UserPreferences
from app.session_store.base import SessionPayload, SessionStore
from app.app_types import CachedConditions, CachedAssessment

from utils.logging_utils import get_tagged_logger

logger = get_tagged_logger(__name__, tag="in_memory_session_store")


class InMemorySessionStore(SessionStore):
    """Thread-safe, TTL-aware in-memory store (dev/test)."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        """Initialize the store with a TTL (seconds)."""
        logger.debug("Initializing InMemorySessionStore")
        self.ttl = ttl_seconds
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _expired(self, exp: float) -> bool:
        """Return True if an expiry timestamp is in the past."""
        return exp < time.monotonic()

    def _generate_id(self) -> str:
        """Generate a new session id."""
        return str(uuid.uuid4())

    def create_session(self, messages, preferences=None, conditions: Optional[CachedConditions] = None, assessment: Optional[CachedAssessment] = None) -> str:
        """Create a new session and return its id."""
        with self._lock:
            sid = self._generate_id()
            self._sessions[sid] = {
                "messages": messages,
                "preferences": preferences or UserPreferences(),
                "conditions": conditions,
                "assessment": assessment,
                "exp": time.monotonic() + self.ttl,
            }
            return sid

    def get_session(self, session_id: str) -> Optional[SessionPayload]:
        """Return the session payload, refreshing TTL, or None if missing/expired."""
        with self._lock:
            data = self._sessions.get(session_id)
            if not data:
                return None
            if self._expired(data["exp"]):
                self._sessions.pop(session_id, None)
                return None
            # refresh TTL on access
            data["exp"] = time.monotonic() + self.ttl
            return data["messages"], data["preferences"], data.get("conditions"), data.get("assessment")

    def update_session(self, session_id: str, messages=None, preferences=None, conditions: Optional[CachedConditions] = None, assessment: Optional[CachedAssessment] = None) -> None:
        """Update a session in place; no-op if missing/expired."""
        with self._lock:
            data = self._sessions.get(session_id)
            if not data or self._expired(data["exp"]):
                self._sessions.pop(session_id, None)
                return
            if messages is not None:
                data["messages"] = messages
            if preferences is not None:
                data["preferences"] = preferences
            if conditions is not None:
                data["conditions"] = conditions
            if assessment is not None:
                data["assessment"] = assessment
            data["exp"] = time.monotonic() + self.ttl

    def delete_session(self, session_id: str) -> None:
        """Remove a session if it exists."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear(self) -> None:
        """Clear all sessions."""
        with self._lock:
            self._sessions.clear()
