"""Redis-backed session store with TTL."""

import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from app.agent import UserPreferences
from app.session_store.base import SessionPayload, SessionStore
from app.app_types import CachedConditions, CachedAssessment
from app.forecast_service import BikeConditions, BikeHourConditions
from app.domain import AgentAssessmentPayload
from utils.logging_utils import get_tagged_logger

logger = get_tagged_logger(__name__, tag="session_store/redis_session_store")


class RedisSessionStore(SessionStore):
    """Redis-backed sessions with TTL. Stores payload via pickle."""

    def __init__(
        self,
        client,
        ttl_seconds: int = 3600,
        max_age_seconds: int | None = None,
        prefix: str = "session:",
    ) -> None:
        """Initialize with a Redis client, TTL, and optional absolute max age."""
        logger.debug("Initializing RedisSessionStore")
        self.client = client
        self.ttl = ttl_seconds
        self.max_age = max_age_seconds
        self.prefix = prefix

    def _key(self, session_id: str) -> str:
        """Return the Redis key for a session id."""
        return f"{self.prefix}{session_id}"

    def _generate_id(self) -> str:
        """Generate a new session id."""
        return str(uuid.uuid4())

    def _safe_dump(self, payload: SessionPayload, *, created_at: float) -> bytes | None:
        """Serialize a session payload to JSON bytes."""
        try:
            messages, prefs, conditions, assessment = payload
            data = {
                "messages": messages,
                "preferences": (prefs or UserPreferences()).model_dump(),
                "conditions": self._serialize_conditions(conditions),
                "assessment": self._serialize_assessment(assessment),
                "created_at": created_at,
            }
            return json.dumps(data, default=self._json_default).encode("utf-8")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to serialize session payload: %s", exc)
            return None

    def _safe_load(self, raw: bytes) -> Optional[tuple[SessionPayload, float]]:
        """Deserialize JSON bytes into a session payload and created_at."""
        try:
            data = json.loads(raw.decode("utf-8"))
            messages = data.get("messages")
            prefs = UserPreferences(**(data.get("preferences") or {}))
            conditions = self._deserialize_conditions(data.get("conditions"))
            assessment = self._deserialize_assessment(data.get("assessment"))
            created_at = data.get("created_at") or time.time()
            return (messages, prefs, conditions, assessment), float(created_at)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to deserialize session payload: %s", exc)
            return None

    def _is_expired(self, created_at: float) -> bool:
        """Return True if the session exceeds absolute max age."""
        if self.max_age is None:
            return False
        return (time.time() - created_at) > self.max_age

    def _ttl_remaining(self, created_at: float) -> int:
        """Return TTL seconds capped by absolute max age."""
        if self.max_age is None:
            return self.ttl
        remaining = int(max(0.0, (created_at + self.max_age) - time.time()))
        return min(self.ttl, remaining)

    @staticmethod
    def _json_default(obj):
        """Provide JSON serialization for datetimes and dataclasses."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        try:
            return asdict(obj)
        except Exception:
            return str(obj)

    @staticmethod
    def _serialize_bike_conditions(cond: BikeConditions | None):
        """Serialize bike conditions to a JSON-safe dict."""
        if not cond:
            return None

        def hour_to_dict(hour: BikeHourConditions | None):
            if not hour:
                return None
            d = asdict(hour)
            if hour.time:
                d["time"] = hour.time.isoformat()
            return d

        return {
            "current": hour_to_dict(cond.current),
            "forecast": [hour_to_dict(h) for h in cond.forecast],
        }

    def _serialize_conditions(self, conditions: CachedConditions | None):
        """Serialize cached conditions with timestamps."""
        if not conditions:
            return None
        return {
            "fetched_at": conditions.fetched_at.isoformat() if conditions.fetched_at else None,
            "data": self._serialize_bike_conditions(conditions.data),
        }

    @staticmethod
    def _deserialize_bike_conditions(data: dict | None) -> BikeConditions | None:
        """Deserialize bike conditions from a JSON-safe dict."""
        if not data:
            return None

        def hour_from_dict(d: dict | None) -> BikeHourConditions | None:
            """Convert a dict to a BikeHourConditions object."""
            if not d:
                return None
            time_val = d.get("time")
            if time_val:
                d = {**d, "time": datetime.fromisoformat(time_val)}
            return BikeHourConditions(**d)

        current = hour_from_dict(data.get("current"))
        forecast = [hour_from_dict(item) for item in (data.get("forecast") or []) if item]
        return BikeConditions(current=current, forecast=forecast)

    def _deserialize_conditions(self, data: dict | None) -> CachedConditions | None:
        """Deserialize cached conditions with timestamps."""
        if not data:
            return None
        fetched_at = data.get("fetched_at")
        fetched_dt = datetime.fromisoformat(fetched_at) if fetched_at else None
        cond = self._deserialize_bike_conditions(data.get("data"))
        if fetched_dt and cond:
            return CachedConditions(data=cond, fetched_at=fetched_dt)
        return None

    @staticmethod
    def _serialize_assessment(assessment: CachedAssessment | None):
        """Serialize cached assessment metadata."""
        if not assessment:
            return None
        return {
            "generated_at": assessment.generated_at.isoformat() if assessment.generated_at else None,
            "data": assessment.data.model_dump() if assessment.data else None,
        }

    @staticmethod
    def _deserialize_assessment(data: dict | None) -> CachedAssessment | None:
        """Deserialize cached assessment metadata."""
        if not data:
            return None
        generated_at_raw = data.get("generated_at")
        generated_at = datetime.fromisoformat(generated_at_raw) if generated_at_raw else None
        payload = data.get("data")
        assessment_payload = AgentAssessmentPayload.model_validate(payload) if payload else None
        if generated_at and assessment_payload:
            return CachedAssessment(data=assessment_payload, generated_at=generated_at)
        return None

    def create_session(self, messages, preferences=None, conditions: Optional[CachedConditions] = None,
                       assessment: Optional[CachedAssessment] = None) -> str:
        """Create and persist a new session, returning its id."""
        sid = self._generate_id()
        created_at = time.time()
        payload = self._safe_dump(
            (messages, preferences or UserPreferences(), conditions, assessment),
            created_at=created_at,
        )
        if payload is None:
            raise RuntimeError("Failed to serialize session payload")
        try:
            ttl = self._ttl_remaining(created_at)
            if ttl <= 0:
                raise RuntimeError("Session max age expired before storage")
            self.client.setex(self._key(sid), ttl, payload)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to write session to Redis: %s", exc)
            raise
        return sid

    def get_session(self, session_id: str) -> Optional[SessionPayload]:
        """Fetch a session payload, refreshing TTL, or None if missing/invalid."""
        try:
            raw = self.client.get(self._key(session_id))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to read session from Redis: %s", exc)
            return None
        if not raw:
            return None
        loaded = self._safe_load(raw)
        if not loaded:
            return None
        payload, created_at = loaded
        if self._is_expired(created_at):
            self.delete_session(session_id)
            return None
        try:
            ttl = self._ttl_remaining(created_at)
            if ttl > 0:
                self.client.expire(self._key(session_id), ttl)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to refresh session TTL: %s", exc)
        return payload

    def update_session(self, session_id: str, messages=None, preferences=None, conditions: Optional[CachedConditions] = None, assessment: Optional[CachedAssessment] = None) -> None:
        """Update an existing session; silently no-ops if missing/invalid."""
        key = self._key(session_id)
        try:
            raw = self.client.get(key)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to read session from Redis for update: %s", exc)
            return
        if not raw:
            return
        loaded = self._safe_load(raw)
        if not loaded:
            return
        payload, created_at = loaded
        if self._is_expired(created_at):
            self.delete_session(session_id)
            return
        msgs, prefs, conds, assess = payload
        if messages is not None:
            msgs = messages
        if preferences is not None:
            prefs = preferences
        if conditions is not None:
            conds = conditions
        if assessment is not None:
            assess = assessment
        serialized = self._safe_dump((msgs, prefs, conds, assess), created_at=created_at)
        if serialized is None:
            return
        try:
            ttl = self._ttl_remaining(created_at)
            if ttl <= 0:
                self.delete_session(session_id)
                return
            self.client.setex(key, ttl, serialized)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to update session in Redis: %s", exc)

    def delete_session(self, session_id: str) -> None:
        """Delete a session if present."""
        try:
            self.client.delete(self._key(session_id))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to delete session from Redis: %s", exc)

    def clear(self) -> None:
        """Best-effort clear for all sessions under the configured prefix."""
        try:
            for key in self.client.scan_iter(f"{self.prefix}*"):
                self.client.delete(key)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to clear sessions from Redis: %s", exc)
