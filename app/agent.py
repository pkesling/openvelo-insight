from __future__ import annotations

"""
LLM-facing agent orchestration: builds deterministic assessments and asks the
LLM to narrate them. All scoring/window logic is deterministic.
"""

import os
from datetime import datetime, timezone
from typing import Optional, Tuple

from pydantic import BaseModel, Field

from .assessment_engine import assess_timeline, compute_window_recommendations, build_summary
from .domain import AgentAssessmentPayload, AssessmentContext, RiderPreferences
from .forecast_service import BikeConditions
from .narration import SYSTEM_PROMPT_HYBRID, build_narration_messages, validate_narration_output
from .ollama_client import ollama_client
from utils.logging_utils import get_tagged_logger

logger = get_tagged_logger(__name__, tag="app/agent")


class UserPreferences(BaseModel):
    """User-tunable riding preferences that influence recommendations."""
    latitude: float = float(os.getenv("USER_LATITUDE_DEFAULT", 43.00))
    longitude: float = float(os.getenv("USER_LONGITUDE_DEFAULT", -89.00))
    timezone: str = Field(default_factory=lambda: os.getenv("USER_TIMEZONE_DEFAULT", "America/Chicago"))
    ride_window_hours: int = 12
    ideal_temp_f: Optional[float] = 75.0
    preferred_temp_range_f: Optional[Tuple[float, float]] = (65.0, 93.0)
    prefer_daylight: bool = True
    max_wind_mph: Optional[float] = 25.0
    avoid_poor_aqi: bool = True
    max_aqi: Optional[int] = 80
    avoid_precip: bool = True


def build_assessment_payload(conditions: BikeConditions, prefs: UserPreferences | None) -> AgentAssessmentPayload:
    """Compute deterministic assessment and window recommendations."""
    prefs = prefs or UserPreferences()   # user provided, or default, values for user riding preferences
    rider_prefs = RiderPreferences(**prefs.model_dump())  # normalized schema for user riding preferences
    current_assessment, hourly_assessments = assess_timeline(rider_prefs, conditions)
    windows = compute_window_recommendations(hourly_assessments)
    summary = build_summary(hourly_assessments, windows)

    return AgentAssessmentPayload(
        context=AssessmentContext(
            generated_at=datetime.now(timezone.utc),
            latitude=prefs.latitude,
            longitude=prefs.longitude,
            timezone=prefs.timezone,
        ),
        preferences=rider_prefs,
        current=current_assessment,
        hourly=hourly_assessments,
        summary=summary,
        policies={},
    )


def narrate_assessment(
    assessment: AgentAssessmentPayload,
    *,
    user_message: str | None = None,
    prior_messages: list[dict] | None = None,
) -> tuple[list[dict], str]:
    """
    Ask the LLM to narrate a deterministic assessment. Returns (messages, assistant_content).
    """
    messages = list(prior_messages) if prior_messages else build_narration_messages(assessment)

    if user_message is not None:
        messages.append({"role": "user", "content": user_message})

    logger.debug(
        "LLM prompt lengths (chars): system=%d latest_user=%d total_msgs=%d",
        len(SYSTEM_PROMPT_HYBRID),
        len(user_message or ""),
        len(messages),
    )
    raw_reply = ollama_client.chat(messages)

    try:
        assistant_content = validate_narration_output(
            raw_reply, assessment.summary.suitability_score if assessment.summary else None
        )
    except Exception as e:
        logger.warning("Narration validation failed; returning raw reply", extra={"error": str(e)})
        assistant_content = raw_reply

    messages.append({"role": "assistant", "content": assistant_content})
    return messages, assistant_content
