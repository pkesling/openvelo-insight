"""HTTP API for the biking conditions assistant."""

import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.domain import AgentAssessmentPayload
from .agent import UserPreferences, build_assessment_payload, narrate_assessment
from .narration import build_narration_messages
from .app_types import CachedConditions
from .config import settings
from .data_sources import build_data_source
from .forecast_service import BikeConditions, get_bike_conditions_for_window
from .session_manager import create_session, get_session, update_session
from utils.logging_utils import get_tagged_logger

logger = get_tagged_logger(__name__, tag="app/api")

# Optional Redis client for API key checks; fallback to a static key
try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover - exercised implicitly
    redis = None

_redis_client = None
if settings.api_key_redis_url and redis:
    try:
        _redis_client = redis.Redis.from_url(settings.api_key_redis_url)
        logger.info("API key checks will use Redis backend", extra={"redis_url": settings.api_key_redis_url})
    except Exception as exc:  # pragma: no cover - safety net
        logger.warning("Failed to connect to Redis for API key checks; falling back to static key",
                       extra={"error": str(exc)})


def require_api_key(x_api_key: str | None = Header(default=None)):
    """
    Validate X-API-Key header against Redis (if configured) or the static api_key setting.
    """
    # If no key configured anywhere, allow requests (dev/default mode).
    if not settings.api_key and not _redis_client:
        if not settings.api_key:
            logger.debug("No API key configured; allowing all requests")
        if not _redis_client:
            logger.debug("No Redis client configured; allowing all requests")

        return

    if not x_api_key:
        logger.debug("No API key provided")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

    # First, try Redis, if available
    if _redis_client:
        logger.debug("Checking API key against Redis")
        try:
            if _redis_client.sismember(settings.api_key_redis_set, x_api_key):
                return
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Redis API key lookup error; falling back to static key",
                           extra={"error": str(e)})

    # Fallback to static key comparison
    if settings.api_key and hmac.compare_digest(str(x_api_key), str(settings.api_key)):
        logger.debug("API key not found in Redis; checking static key.")
        return

    logger.debug("Invalid API key provided")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


router = APIRouter(dependencies=[Depends(require_api_key)])
DATA_SOURCE = build_data_source(settings)


class CurrentConditions(BaseModel):
    """Serialized weather/air metrics used in API responses."""
    timestamp_utc: datetime
    temperature: Optional[str] = None
    relative_humidity: Optional[str] = None
    dew_point: Optional[str] = None
    apparent_temperature: Optional[str] = None
    precipitation_prob: Optional[str] = None
    precipitation: Optional[str] = None
    cloud_cover: Optional[str] = None
    wind_speed: Optional[str] = None
    wind_gusts: Optional[str] = None
    wind_direction: Optional[str] = None
    is_day: Optional[str] = None
    pm2_5: Optional[str] = None
    pm10: Optional[str] = None
    us_aqi: Optional[str] = None
    ozone: Optional[str] = None
    uv_index: Optional[str] = None


class ChatRequest(BaseModel):
    """Incoming chat message payload."""
    message: str


class StartResponse(BaseModel):
    """Session bootstrap response with conditions and optional assessment."""
    session_id: str
    initial_response: str | None = None   # markdown for the chat bubble
    current_conditions: CurrentConditions | None = None
    forecast: list[CurrentConditions] | None = None
    preferences: UserPreferences | None = None
    assessment: AgentAssessmentPayload | None = None


class ChatResponse(BaseModel):
    """Chat response payload that includes the LLM reply and assessment."""
    response: str                      # markdown for the chat bubble
    assessment: AgentAssessmentPayload | None = None


class PreferencesRequest(UserPreferences):
    """Incoming preferences payload."""
    pass


class PreferencesResponse(BaseModel):
    """Preferences response payload."""
    preferences: UserPreferences


def _get_bike_conditions(conditions: BikeConditions) -> Optional[CurrentConditions]:
    """Convert current BikeConditions into serialized API shape."""
    current = conditions.current.to_display_strings() if conditions.current else None
    if not current:
        return None
    return CurrentConditions(**current)


def _get_forecast_conditions(conditions: BikeConditions) -> list[CurrentConditions]:
    """Convert forecast hours into serialized API shape."""
    out: list[CurrentConditions] = []
    for hour in conditions.forecast or []:
        s = hour.to_display_strings()
        if s:
            out.append(CurrentConditions(**s))
    return out


def _format_summary_markdown(summary) -> str:
    """Render an assessment summary as short markdown."""
    if not summary:
        return ""
    def _label(value) -> str:
        if value is None:
            return ""
        raw = getattr(value, "value", value)
        return str(raw).replace("_", " ").title()

    def _score(value: float | None) -> str:
        if value is None:
            return "n/a"
        return f"{value:.1f}"

    lines = [
        f"**Ride decision:** {_label(summary.overall_decision)}",
        f"**Suitability score:** {_score(summary.suitability_score)}",
    ]
    if summary.primary_limiters:
        limiter_text = ", ".join(
            f"{_label(lim.code)} ({_label(lim.severity)})" for lim in summary.primary_limiters
        )
        lines.append(f"**Risks:** {limiter_text}")
    if summary.best_windows:
        best = summary.best_windows[0]
        lines.append(
            f"**Best window:** {best.start.isoformat()} to {best.end.isoformat()} (score {best.window_score})"
        )
    return "\n".join(lines)


def _resolve_time_window(prefs: UserPreferences) -> tuple[str, ZoneInfo, datetime, datetime]:
    """Resolve timezone and compute the rider's preferred window."""
    tz_str = prefs.timezone or "America/Chicago"
    try:
        tz = ZoneInfo(tz_str)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {tz_str}")
    start_time = datetime.now(tz)
    end_time = start_time + timedelta(hours=prefs.ride_window_hours)
    return tz_str, tz, start_time, end_time


def _fetch_conditions(
    prefs: UserPreferences,
    start_time: datetime,
    end_time: datetime,
    tz_str: str,
    cached: CachedConditions | BikeConditions | dict | None = None,
    require_fresh: bool = False,
) -> BikeConditions:
    """Fetch conditions, using cached values when still fresh."""
    if cached and (not require_fresh or _conditions_are_fresh(cached)):
        unwrapped = _unwrap_conditions(cached)
        if unwrapped:
            return unwrapped
    return get_bike_conditions_for_window(
        latitude=prefs.latitude,
        longitude=prefs.longitude,
        timezone=tz_str,
        start_local=start_time,
        end_local=end_time,
        forecast_hours=settings.forecast_hours,
        data_source=DATA_SOURCE,
    )


def _ensure_conditions_present(conditions: BikeConditions) -> None:
    """Raise a 404 if current or forecast data is missing."""
    if not conditions.current:
        raise HTTPException(status_code=404, detail="No current weather data available.")
    if not conditions.forecast:
        raise HTTPException(status_code=404, detail="No forecast data available.")


def _wrap_conditions(conditions: BikeConditions) -> CachedConditions:
    """Attach a timestamp so we can enforce a freshness TTL."""
    return CachedConditions(data=conditions, fetched_at=datetime.now(tz=timezone.utc))


def _unwrap_conditions(value: CachedConditions | BikeConditions | dict | None) -> Optional[BikeConditions]:
    """Return BikeConditions from supported cache wrappers."""
    if not value:
        return None
    if isinstance(value, BikeConditions):
        return value
    if isinstance(value, dict):
        data = value.get("data")
        return data if isinstance(data, BikeConditions) else None
    if isinstance(value, CachedConditions):
        return value.data
    return None


def _conditions_are_fresh(value: CachedConditions | BikeConditions | dict | None) -> bool:
    """Check whether cached conditions are within the TTL window."""
    if not value:
        return False
    if isinstance(value, BikeConditions):
        return True  # legacy/raw payload; treat as fresh
    if isinstance(value, dict):
        ts = value.get("fetched_at")
        if isinstance(ts, datetime):
            age = datetime.now(tz=timezone.utc) - ts
            return age.total_seconds() < settings.conditions_ttl_seconds
        return False
    if isinstance(value, CachedConditions):
        age = datetime.now(tz=timezone.utc) - value.fetched_at
        return age.total_seconds() < settings.conditions_ttl_seconds
    return False


def default_preferences() -> UserPreferences:
    """Create preferences using defaults/env overrides."""
    # Single source of truth: defer to UserPreferences defaults/env overrides
    prefs = UserPreferences()
    logger.debug(f"Using default preferences: {prefs}")
    return prefs


@router.post("/session/start", response_model=StartResponse)
def start_session():
    """Create a new session and return current conditions/forecast."""
    prefs = default_preferences()
    tz_str, _tz, start_time, end_time = _resolve_time_window(prefs)

    logger.info(f"Starting session for {tz_str} at {start_time}")
    logger.info(f"User preferences: {prefs}")
    logger.info(f"Getting weather conditions for {start_time} to {end_time}")
    conditions = _fetch_conditions(prefs, start_time, end_time, tz_str)
    _ensure_conditions_present(conditions)

    logger.debug(f"Got weather conditions: {conditions}")

    # Create empty session; a client will trigger initial LLM call separately so it can show
    # preferences/conditions immediately.
    session_id = create_session([], prefs, _wrap_conditions(conditions))

    return StartResponse(
        session_id=session_id,
        initial_response=None,
        current_conditions=_get_bike_conditions(conditions),
        forecast=_get_forecast_conditions(conditions),
        preferences=prefs,
    )


@router.post("/session/{session_id}/initial", response_model=StartResponse)
def run_initial(session_id: str):
    """Run the initial assessment/narration for an existing session."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session ID")

    _messages, prefs, conditions_cached, _assessment = session
    tz_str, _tz, start_time, end_time = _resolve_time_window(prefs)

    conditions = _fetch_conditions(
        prefs,
        start_time,
        end_time,
        tz_str,
        cached=conditions_cached,
        require_fresh=True,
    )
    _ensure_conditions_present(conditions)

    assessment_payload = build_assessment_payload(conditions, prefs)
    base_messages = build_narration_messages(assessment_payload)
    initial_response = _format_summary_markdown(assessment_payload.summary)
    if initial_response:
        base_messages = [
            *base_messages,
            {"role": "assistant", "content": initial_response},
        ]

    try:
        update_session(
            session_id,
            messages=base_messages,
            preferences=prefs,
            conditions=_wrap_conditions(conditions),
            assessment=assessment_payload,
        )
    except TypeError:
        update_session(session_id, messages=base_messages, preferences=prefs, conditions=_wrap_conditions(conditions))

    return StartResponse(
        session_id=session_id,
        initial_response=initial_response,
        current_conditions=_get_bike_conditions(conditions),
        forecast=_get_forecast_conditions(conditions),
        preferences=prefs,
        assessment=assessment_payload,
    )


@router.post("/session/{session_id}/chat", response_model=ChatResponse)
def continue_chat(session_id: str, req: ChatRequest):
    """Append a user message, narrate assessment, and persist state."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session ID")

    if len(req.message) > settings.max_user_message_chars:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Message too long; limit {settings.max_user_message_chars} characters.")

    messages, prefs, conditions_cached, assessment = session
    tz_str, _tz, start_time, end_time = _resolve_time_window(prefs)

    cached_is_fresh = _conditions_are_fresh(conditions_cached)
    conditions = _fetch_conditions(
        prefs,
        start_time,
        end_time,
        tz_str,
        cached=conditions_cached,
        require_fresh=True,
    )
    _ensure_conditions_present(conditions)

    if assessment is None or not cached_is_fresh:
        assessment = build_assessment_payload(conditions, prefs)

    messages, assistant_content = narrate_assessment(
        assessment, user_message=req.message, prior_messages=messages or None
    )

    update_kwargs = {"messages": messages, "assessment": assessment}
    if not cached_is_fresh:
        update_kwargs["conditions"] = _wrap_conditions(conditions)
    update_session(session_id, **update_kwargs)

    return ChatResponse(response=assistant_content, assessment=assessment)


@router.get("/session/{session_id}/preferences", response_model=PreferencesResponse)
def get_preferences(session_id: str):
    """Return stored preferences for a session."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session ID")
    _messages, prefs, _conditions, _assessment = session
    return PreferencesResponse(preferences=prefs or UserPreferences())


@router.post("/session/{session_id}/preferences", response_model=PreferencesResponse)
def set_preferences(session_id: str, prefs: PreferencesRequest):
    """Update stored preferences for a session."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session ID")

    messages, _current_prefs, conditions, _assessment = session
    update_session(session_id, preferences=prefs, conditions=conditions, messages=messages)
    return PreferencesResponse(preferences=prefs)


@router.post("/session/{session_id}/refresh", response_model=StartResponse)
def refresh_outlook(session_id: str):
    """Refresh weather/assessment for an existing session."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session ID")

    messages, prefs, _conditions, _assessment = session

    tz_str, _tz, start_time, end_time = _resolve_time_window(prefs)

    conditions = _fetch_conditions(prefs, start_time, end_time, tz_str)
    _ensure_conditions_present(conditions)

    assessment = build_assessment_payload(conditions, prefs)
    update_session(
        session_id,
        messages=messages,
        preferences=prefs,
        conditions=_wrap_conditions(conditions),
        assessment=assessment,
    )

    return StartResponse(
        session_id=session_id,
        initial_response="",
        current_conditions=_get_bike_conditions(conditions),
        forecast=_get_forecast_conditions(conditions),
        preferences=prefs,
        assessment=assessment,
    )
