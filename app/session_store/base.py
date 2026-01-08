"""Shared protocol and types for session storage backends."""

from typing import Any, Optional, Protocol, Tuple

from app.agent import UserPreferences
from app.app_types import CachedConditions, CachedAssessment

SessionPayload = Tuple[Any, UserPreferences, Optional[CachedConditions], Optional[CachedAssessment]]


class SessionStore(Protocol):
    """Protocol for session storage backends."""
    def create_session(
        self,
        messages: Any,
        preferences: Optional[UserPreferences] = None,
        conditions: Optional[CachedConditions] = None,
        assessment: Optional[CachedAssessment] = None,
    ) -> str:
        """Persist a new session and return its id."""

    def get_session(self, session_id: str) -> Optional[SessionPayload]:
        """Fetch a session by id, returning None if missing or expired."""

    def update_session(
        self,
        session_id: str,
        messages: Any = None,
        preferences: Optional[UserPreferences] = None,
        conditions: Optional[CachedConditions] = None,
        assessment: Optional[CachedAssessment] = None,
    ) -> None:
        """Update fields on an existing session, ignoring missing/expired ids."""

    def delete_session(self, session_id: str) -> None:
        """Delete a session without raising if it is absent."""

    def clear(self) -> None:
        """Clear all stored sessions."""
