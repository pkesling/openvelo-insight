"""Shared dataclasses and lightweight types used across modules."""

from dataclasses import dataclass
from datetime import datetime

from app.forecast_service import BikeConditions
from app.domain import AgentAssessmentPayload


@dataclass
class CachedConditions:
    """BikeConditions payload with the timestamp it was fetched."""
    data: BikeConditions
    fetched_at: datetime


@dataclass
class CachedAssessment:
    """Deterministic assessment payload cached with timestamp."""
    data: AgentAssessmentPayload
    generated_at: datetime
