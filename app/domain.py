"""Domain vocabulary and strict schemas for deterministic ride assessments.

This module defines the stable contract between the numeric analysis engine and
any LLM narrator: enums, risk codes, policies, and Pydantic models for the
payloads that flow through the system. No interpretation logic lives here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Tuple

from pydantic import BaseModel, ConfigDict, Field


class _StrictBaseModel(BaseModel):
    """Base model with strict extra handling."""

    model_config = ConfigDict(extra="forbid")


class Status(str, Enum):
    """Judgment status for a single measure."""
    IDEAL = "ideal"
    ACCEPTABLE = "acceptable"
    CAUTION = "caution"
    AVOID = "avoid"
    UNKNOWN = "unknown"


class Trend(str, Enum):
    """Trend direction for a measure over time."""
    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"
    UNKNOWN = "unknown"


class Decision(str, Enum):
    """Overall go/no-go decision for a time slice."""
    GO = "go"
    GO_WITH_CAUTION = "go_with_caution"
    AVOID = "avoid"
    UNKNOWN = "unknown"


class RiskSeverity(str, Enum):
    """Severity levels used for risk flags."""
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    CRITICAL = "critical"


class Priority(str, Enum):
    """Priority level for surfacing risks or notes."""
    INFO = "info"
    NORMAL = "normal"
    ELEVATED = "elevated"
    URGENT = "urgent"


class RiskCode(str, Enum):
    """Canonical codes for common riding risks."""
    EXTREME_HEAT = "extreme_heat"
    EXTREME_COLD = "extreme_cold"
    HIGH_WIND = "high_wind"
    GUSTY_WIND = "gusty_wind"
    PRECIPITATION = "precipitation"
    STORM = "storm"
    SNOW_OR_ICE = "snow_or_ice"
    LOW_VISIBILITY = "low_visibility"
    DARKNESS = "darkness"
    POOR_AIR_QUALITY = "poor_air_quality"
    UV_EXPOSURE = "uv_exposure"
    ROUTE_HAZARD = "route_hazard"


class MeasureDirectionality(str, Enum):
    """How a measure should trend to be considered better."""
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    TARGET_BAND = "target_band"
    UNKNOWN = "unknown"


class MeasurePolicy(_StrictBaseModel):
    """Policy metadata for a measure used in scoring and trends."""
    name: str
    unit: str | None = None
    trend_deadband: float | None = None
    directionality: MeasureDirectionality = MeasureDirectionality.UNKNOWN


DEFAULT_MEASURE_POLICIES: Dict[str, MeasurePolicy] = {
    "temperature_f": MeasurePolicy(
        name="temperature_f",
        unit="F",
        trend_deadband=1.0,
        directionality=MeasureDirectionality.TARGET_BAND,
    ),
    "apparent_temperature_f": MeasurePolicy(
        name="apparent_temperature_f",
        unit="F",
        trend_deadband=1.0,
        directionality=MeasureDirectionality.TARGET_BAND,
    ),
    "wind_speed_mph": MeasurePolicy(
        name="wind_speed_mph",
        unit="mph",
        trend_deadband=1.0,
        directionality=MeasureDirectionality.LOWER_IS_BETTER,
    ),
    "wind_gusts_mph": MeasurePolicy(
        name="wind_gusts_mph",
        unit="mph",
        trend_deadband=2.0,
        directionality=MeasureDirectionality.LOWER_IS_BETTER,
    ),
    "us_aqi": MeasurePolicy(
        name="us_aqi",
        unit="aqi",
        trend_deadband=3.0,
        directionality=MeasureDirectionality.LOWER_IS_BETTER,
    ),
    "precipitation_prob_percent": MeasurePolicy(
        name="precipitation_prob_percent",
        unit="percent",
        trend_deadband=5.0,
        directionality=MeasureDirectionality.LOWER_IS_BETTER,
    ),
    "precipitation_mm": MeasurePolicy(
        name="precipitation_mm",
        unit="mm",
        trend_deadband=0.1,
        directionality=MeasureDirectionality.LOWER_IS_BETTER,
    ),
    "uv_index": MeasurePolicy(
        name="uv_index",
        unit="uv",
        trend_deadband=0.2,
        directionality=MeasureDirectionality.LOWER_IS_BETTER,
    ),
}


class MeasureJudgment(_StrictBaseModel):
    """Judgment for a single measure within an hour."""
    status: Status
    distance_from_preference: float | None = None
    severity: RiskSeverity | None = None
    reasons: List[str] = Field(default_factory=list)
    trend: Trend | None = None
    trend_delta: float | None = None
    trend_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RiskFlag(_StrictBaseModel):
    """Structured risk annotation tied to a judgment."""
    code: RiskCode
    severity: RiskSeverity
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    priority: Priority = Priority.NORMAL
    evidence: List[str] = Field(default_factory=list)


class HourAssessment(_StrictBaseModel):
    """Assessment output for a single hour."""
    time: datetime
    hour_index: int | None = None
    decision: Decision | None = None
    judgments: Dict[str, MeasureJudgment] = Field(default_factory=dict)
    risks: List[RiskFlag] = Field(default_factory=list)
    hour_score: float | None = None
    notes: List[str] = Field(default_factory=list)


class WindowRecommendation(_StrictBaseModel):
    """Recommended ride window with aggregated scoring."""
    start: datetime
    end: datetime
    duration: timedelta | None = None
    decision: Decision
    window_score: float | None = None
    reasons: List[str] = Field(default_factory=list)
    risks: List[RiskFlag] = Field(default_factory=list)


class AssessmentSummary(_StrictBaseModel):
    """Summary of overall suitability and top risks."""
    overall_decision: Decision = Decision.UNKNOWN
    suitability_score: float | None = None
    primary_limiters: List[RiskFlag] = Field(default_factory=list)
    best_windows: List[WindowRecommendation] = Field(default_factory=list)


class RiderPreferences(_StrictBaseModel):
    """Normalized user preferences used for scoring."""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    ride_window_hours: int | None = None
    ideal_temp_f: float | None = None
    preferred_temp_range_f: Tuple[float, float] | None = None
    prefer_daylight: bool | None = None
    max_wind_mph: float | None = None
    avoid_poor_aqi: bool | None = None
    max_aqi: int | None = None
    avoid_precip: bool | None = None


class AssessmentContext(_StrictBaseModel):
    """Metadata describing how/when an assessment was generated."""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    generated_at: datetime | None = None
    source: str | None = None


class AgentAssessmentPayload(_StrictBaseModel):
    """Full deterministic payload used for narration and UI."""
    context: AssessmentContext
    preferences: RiderPreferences
    current: HourAssessment | None = None
    hourly: List[HourAssessment] = Field(default_factory=list)
    summary: AssessmentSummary | None = None
    policies: Dict[str, MeasurePolicy] = Field(default_factory=dict)
