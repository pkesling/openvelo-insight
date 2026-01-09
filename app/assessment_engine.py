"""Deterministic single-hour assessment logic.

This module converts a raw hour snapshot + rider preferences into a structured
HourAssessment with per-measure judgments and risk flags. No trend/window logic
is included here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil
from typing import Any, Mapping, Sequence

from app.domain import (
    Decision,
    HourAssessment,
    MeasureJudgment,
    RiderPreferences,
    RiskCode,
    RiskFlag,
    RiskSeverity,
    Status,
    Trend,
    AssessmentSummary,
    DEFAULT_MEASURE_POLICIES,
    MeasurePolicy,
    MeasureDirectionality,
    WindowRecommendation,
)
from app.forecast_service import BikeConditions


def _get_field(hour: Any, key: str, default=None):
    """Support attribute, dict, or Mapping access for hour snapshots."""
    if hour is None:
        return default
    if isinstance(hour, Mapping):
        return hour.get(key, default)
    return getattr(hour, key, default)


def _clamp_score(score: float) -> float:
    """Clamp a score to the 0-10 range."""
    return max(0.0, min(10.0, score))


def _add_risk(risks: list[RiskFlag], code: RiskCode, severity: RiskSeverity, evidence: Sequence[str]):
    """Append a risk flag with evidence to the running list."""
    risks.append(RiskFlag(code=code, severity=severity, evidence=list(evidence)))


def _judge_temperature(temp_f: float | None, prefs: RiderPreferences, risks: list[RiskFlag]) -> MeasureJudgment:
    """Judge temperature against rider preferences and flag risks."""
    reasons: list[str] = []
    distance = None  # distance from preferred range
    severity = None  # risk severity

    range_pref = prefs.preferred_temp_range_f
    if temp_f is None or range_pref is None:
        return MeasureJudgment(status=Status.UNKNOWN, reasons=reasons)

    lower, upper = range_pref
    distance = 0.0

    if temp_f < lower:
        distance = lower - temp_f
        if temp_f < 32:
            # somewhat arbitrarily limit cold risk at 32 F and major cold risk at 25 F
            severity = RiskSeverity.MAJOR if temp_f <= 25 else RiskSeverity.MODERATE
            reasons.append(f"Very cold: {temp_f:.1f}F below preferred {lower:.1f}F")
            _add_risk(risks, RiskCode.EXTREME_COLD, severity, reasons)
            return MeasureJudgment(status=Status.AVOID, distance_from_preference=distance,
                                   severity=severity, reasons=reasons)
        # adjust severity based on the distance from the preferred temperature, penalizing temps far outside preferences
        if distance > 20:
            severity = RiskSeverity.MODERATE
            reasons.append(f"Cold: {temp_f:.1f}F is {distance:.1f}F below preferred")
            _add_risk(risks, RiskCode.EXTREME_COLD, severity, reasons)
            return MeasureJudgment(status=Status.CAUTION, distance_from_preference=distance,
                                   severity=severity, reasons=reasons)
        if distance > 10:
            severity = RiskSeverity.MODERATE
            reasons.append(f"Cold: {temp_f:.1f}F is {distance:.1f}F below preferred")
            _add_risk(risks, RiskCode.EXTREME_COLD, severity, reasons)
            return MeasureJudgment(status=Status.CAUTION, distance_from_preference=distance,
                                   severity=severity, reasons=reasons)
        if distance > 5:
            reasons.append(f"Slightly cool: {temp_f:.1f}F below preferred")
            return MeasureJudgment(status=Status.ACCEPTABLE, distance_from_preference=distance, reasons=reasons)

        reasons.append(f"Slightly cool: {temp_f:.1f}F just below preferred")
        return MeasureJudgment(status=Status.ACCEPTABLE, distance_from_preference=distance, reasons=reasons)

    if temp_f > upper:
        distance = temp_f - upper
        if distance > 15:
            severity = RiskSeverity.MAJOR
            reasons.append(f"Very hot: {temp_f:.1f}F above preferred {upper:.1f}F")
            _add_risk(risks, RiskCode.EXTREME_HEAT, severity, reasons)
            return MeasureJudgment(status=Status.AVOID, distance_from_preference=distance,
                                   severity=severity, reasons=reasons)
        if distance > 5:
            severity = RiskSeverity.MODERATE
            reasons.append(f"Hot: {temp_f:.1f}F is {distance:.1f}F above preferred")
            _add_risk(risks, RiskCode.EXTREME_HEAT, severity, reasons)
            return MeasureJudgment(status=Status.CAUTION, distance_from_preference=distance,
                                   severity=severity, reasons=reasons)
        reasons.append(f"Slightly warm: {temp_f:.1f}F just above preferred")
        return MeasureJudgment(status=Status.ACCEPTABLE, distance_from_preference=distance, reasons=reasons)

    # temperatures are within the preference range
    reasons.append(f"Comfortable: {temp_f:.1f}F within preferred {lower:.1f}-{upper:.1f}F")
    return MeasureJudgment(status=Status.IDEAL, distance_from_preference=distance, reasons=reasons)


def _judge_wind(wind_mph: float | None, prefs: RiderPreferences, risks: list[RiskFlag]) -> MeasureJudgment:
    """Judge wind speed against rider preferences and flag risks."""
    reasons: list[str] = []
    max_wind = prefs.max_wind_mph or 25.0
    distance = None  # distance from preferred range
    severity = None  # risk severity

    if wind_mph is None:
        return MeasureJudgment(status=Status.UNKNOWN, reasons=reasons)

    if wind_mph > max_wind + 5:
        severity = RiskSeverity.MAJOR
        reasons.append(f"Wind {wind_mph:.1f} mph above limit {max_wind:.1f}")
        _add_risk(risks, RiskCode.HIGH_WIND, severity, reasons)
        return MeasureJudgment(status=Status.AVOID, distance_from_preference=wind_mph - max_wind,
                               severity=severity, reasons=reasons)

    if wind_mph > max_wind:
        severity = RiskSeverity.MODERATE
        reasons.append(f"Wind {wind_mph:.1f} mph exceeds preferred {max_wind:.1f}")
        _add_risk(risks, RiskCode.HIGH_WIND, severity, reasons)
        return MeasureJudgment(status=Status.CAUTION, distance_from_preference=wind_mph - max_wind,
                               severity=severity, reasons=reasons)

    distance = max_wind - wind_mph
    if wind_mph > max_wind * 0.8:
        reasons.append(f"Wind {wind_mph:.1f} mph near limit {max_wind:.1f}")
        return MeasureJudgment(status=Status.ACCEPTABLE, distance_from_preference=distance, reasons=reasons)

    # winds within the preference range
    reasons.append(f"Wind {wind_mph:.1f} mph within preference")
    return MeasureJudgment(status=Status.IDEAL, distance_from_preference=distance, reasons=reasons)


def _judge_gusts(gust_mph: float | None, prefs: RiderPreferences, risks: list[RiskFlag]) -> MeasureJudgment:
    """Judge wind gusts against rider preferences and flag risks."""
    reasons: list[str] = []
    max_wind = prefs.max_wind_mph or 25.0
    distance = None  # distance from preferred range
    severity = None  # risk severity

    if gust_mph is None:
        return MeasureJudgment(status=Status.UNKNOWN, reasons=reasons)

    if gust_mph > max_wind + 15:
        severity = RiskSeverity.MAJOR
        reasons.append(f"Gusts {gust_mph:.1f} mph well above limit {max_wind:.1f}")
        _add_risk(risks, RiskCode.GUSTY_WIND, severity, reasons)
        return MeasureJudgment(status=Status.AVOID, distance_from_preference=gust_mph - max_wind,
                               severity=severity, reasons=reasons)

    if gust_mph > max_wind + 5:
        severity = RiskSeverity.MODERATE
        reasons.append(f"Gusts {gust_mph:.1f} mph above preferred wind")
        _add_risk(risks, RiskCode.GUSTY_WIND, severity, reasons)
        return MeasureJudgment(status=Status.CAUTION, distance_from_preference=gust_mph - max_wind,
                               severity=severity, reasons=reasons)

    if gust_mph > max_wind:
        reasons.append(f"Gusts {gust_mph:.1f} mph slightly above preferred wind")
        return MeasureJudgment(status=Status.ACCEPTABLE, distance_from_preference=gust_mph - max_wind, reasons=reasons)

    distance = max_wind - gust_mph
    reasons.append(f"Gusts {gust_mph:.1f} mph within preference")
    return MeasureJudgment(status=Status.IDEAL, distance_from_preference=distance, reasons=reasons)


def _judge_aqi(aqi: float | None, prefs: RiderPreferences, risks: list[RiskFlag]) -> MeasureJudgment:
    """Judge air quality index against rider preferences and flag risks."""
    reasons: list[str] = []
    distance = None  # distance from preferred range
    severity = None  # risk severity
    max_aqi = prefs.max_aqi or 80
    avoid_poor = prefs.avoid_poor_aqi is not False

    if aqi is None:
        return MeasureJudgment(status=Status.UNKNOWN, reasons=reasons)

    distance = aqi - max_aqi

    if aqi >= 151:
        severity = RiskSeverity.MAJOR
        reasons.append(f"AQI {aqi:.0f} unhealthy")
        _add_risk(risks, RiskCode.POOR_AIR_QUALITY, severity, reasons)
        return MeasureJudgment(status=Status.AVOID, distance_from_preference=distance,
                               severity=severity, reasons=reasons)

    if avoid_poor and aqi > max_aqi:
        severity = RiskSeverity.MODERATE
        reasons.append(f"AQI {aqi:.0f} exceeds preferred max {max_aqi}")
        _add_risk(risks, RiskCode.POOR_AIR_QUALITY, severity, reasons)
        return MeasureJudgment(status=Status.CAUTION, distance_from_preference=distance,
                               severity=severity, reasons=reasons)

    if aqi <= 50:
        reasons.append(f"AQI {aqi:.0f} good")
        return MeasureJudgment(status=Status.IDEAL, distance_from_preference=distance, reasons=reasons)

    reasons.append(f"AQI {aqi:.0f} within preferred range")
    return MeasureJudgment(status=Status.ACCEPTABLE, distance_from_preference=distance, reasons=reasons)


def _judge_precip(prob: float | None, prefs: RiderPreferences, risks: list[RiskFlag]) -> MeasureJudgment:
    """Judge precipitation probability against rider preferences and flag risks."""
    reasons: list[str] = []
    avoid_precip = prefs.avoid_precip is not False
    distance = None  # distance from preferred range
    severity = None  # risk severity

    if prob is None:
        return MeasureJudgment(status=Status.UNKNOWN, reasons=reasons)

    if avoid_precip:
        if prob >= 70:
            severity = RiskSeverity.MODERATE
            reasons.append(f"Precipitation probability {prob:.0f}% high")
            _add_risk(risks, RiskCode.PRECIPITATION, severity, reasons)
            return MeasureJudgment(status=Status.AVOID, distance_from_preference=prob, severity=severity, reasons=reasons)
        if prob >= 50:
            severity = RiskSeverity.MINOR
            reasons.append(f"Precipitation probability {prob:.0f}% elevated")
            _add_risk(risks, RiskCode.PRECIPITATION, severity, reasons)
            return MeasureJudgment(status=Status.CAUTION, distance_from_preference=prob, severity=severity, reasons=reasons)

    if prob >= 80:
        severity = RiskSeverity.MINOR
        reasons.append(f"Precipitation probability {prob:.0f}% may impact ride")
        _add_risk(risks, RiskCode.PRECIPITATION, severity, reasons)
        return MeasureJudgment(status=Status.CAUTION, distance_from_preference=prob, severity=severity, reasons=reasons)

    if prob >= 20:
        reasons.append(f"Precipitation probability {prob:.0f}% low")
        return MeasureJudgment(status=Status.ACCEPTABLE, distance_from_preference=prob, reasons=reasons)

    reasons.append("Precipitation probability minimal")
    return MeasureJudgment(status=Status.IDEAL, distance_from_preference=prob, reasons=reasons)


def _judge_daylight(is_day: bool | None, prefs: RiderPreferences, risks: list[RiskFlag]) -> MeasureJudgment:
    """Judge daylight preference and flag darkness risk."""
    reasons: list[str] = []
    if not prefs.prefer_daylight:
        return MeasureJudgment(status=Status.IDEAL, reasons=reasons)

    if is_day is None:
        return MeasureJudgment(status=Status.UNKNOWN, reasons=reasons)

    if not is_day:
        reasons.append("Riding in darkness")
        _add_risk(risks, RiskCode.DARKNESS, RiskSeverity.MINOR, reasons)
        return MeasureJudgment(status=Status.CAUTION, reasons=reasons)

    reasons.append("Daylight ride")
    return MeasureJudgment(status=Status.IDEAL, reasons=reasons)


def _compute_decision(judgments: dict[str, MeasureJudgment]) -> Decision:
    """Collapse measure judgments into a single decision."""
    statuses = {j.status for j in judgments.values()}
    if Status.AVOID in statuses:
        return Decision.AVOID
    if Status.CAUTION in statuses:
        return Decision.GO_WITH_CAUTION
    if statuses == {Status.UNKNOWN} or not statuses:
        return Decision.UNKNOWN
    return Decision.GO


def _temperature_penalty(distance: float | None) -> float:
    """Return a penalty based on distance from the preferred temperature."""
    if not distance or distance <= 0:
        return 0.0
    scaled = (distance / 10.0) ** 1.5 * 2.0
    return min(4.0, scaled)


def _score_hour(judgments: dict[str, MeasureJudgment]) -> float:
    """Translate measure judgments into a 0-10 suitability score."""
    score = 10.0
    for key, j in judgments.items():
        if j.status == Status.AVOID:
            score -= 4.0
        elif j.status == Status.CAUTION:
            score -= 2.0
        elif j.status == Status.ACCEPTABLE:
            score -= 1.0
        if key == "temperature_f":
            score -= _temperature_penalty(j.distance_from_preference)
    return _clamp_score(score)


def assess_hour(preferences: RiderPreferences, hour_snapshot: Any) -> HourAssessment:
    """Pure function: evaluate a single hour and return a structured assessment."""
    time_val = _get_field(hour_snapshot, "time")
    if not isinstance(time_val, datetime):
        raise ValueError("hour_snapshot.time must be a datetime")

    # read the conditions
    hour_index = _get_field(hour_snapshot, "hour_index")
    temp_f = _get_field(hour_snapshot, "temperature")
    wind_speed = _get_field(hour_snapshot, "wind_speed")
    wind_gusts = _get_field(hour_snapshot, "wind_gusts")
    aqi = _get_field(hour_snapshot, "us_aqi")
    precip_prob = _get_field(hour_snapshot, "precipitation_prob")
    is_day = _get_field(hour_snapshot, "is_day")

    risks: list[RiskFlag] = []
    judgments: dict[str, MeasureJudgment] = {}

    judgments["temperature_f"] = _judge_temperature(temp_f, preferences, risks)
    judgments["wind_speed_mph"] = _judge_wind(wind_speed, preferences, risks)
    judgments["wind_gusts_mph"] = _judge_gusts(wind_gusts, preferences, risks)
    judgments["us_aqi"] = _judge_aqi(aqi, preferences, risks)
    judgments["precipitation_prob_percent"] = _judge_precip(precip_prob, preferences, risks)
    judgments["daylight"] = _judge_daylight(is_day, preferences, risks)

    decision = _compute_decision(judgments)
    hour_score = _score_hour(judgments)

    return HourAssessment(
        time=time_val,
        hour_index=hour_index,
        decision=decision,
        judgments=judgments,
        risks=risks,
        hour_score=hour_score,
        notes=[],
    )


def _trend_direction(value: float, prev: float, policy: MeasurePolicy) -> Trend:
    """
    Compute trend direction given a policy and two points.  For measure policies that assess the trend against
    a range of values (e.g., temperature), value and prev should be the distance to the target band (temperature
    range), not the actual values (temperature).
    """
    delta = value - prev
    deadband = policy.trend_deadband or 0.0
    if abs(delta) <= deadband:
        # if the difference between values is within the deadband, treat as stable (e.g., don't consider a wind speed
        # difference of +1.0 MPH to be worsening)
        return Trend.STABLE

    if policy.directionality == MeasureDirectionality.HIGHER_IS_BETTER:
        return Trend.IMPROVING if delta > 0 else Trend.WORSENING

    if policy.directionality == MeasureDirectionality.LOWER_IS_BETTER:
        return Trend.IMPROVING if delta < 0 else Trend.WORSENING

    #
    # When assessing a MeasureDirectionality.TARGET_BAND, the values (value, prev) passed in are assumed to be
    # a calculation of the distance from the target band.  If the difference between the two "distance" values is
    # negative (the distance to the band is decreasing), then the trend is moving toward the preferred band,
    # which is improving.  If the distance from the band is positive (the distance to the band is increasing),
    # then the trend is worsening.
    #
    return Trend.IMPROVING if delta < 0 else Trend.WORSENING


def _apply_trends(current: HourAssessment, prev: HourAssessment | None, policies: dict[str, MeasurePolicy]) -> None:
    """
    Annotate judgments with trend metadata when possible.

    Trends compare consecutive hours using distance_from_preference values,
    not raw measures. This keeps TARGET_BAND policies consistent across
    measures by interpreting "improving" as moving closer to the preferred
    band (lower distance), and "worsening" as moving away.
    """
    if prev is None:
        return

    for key, judgment in current.judgments.items():
        policy = policies.get(key, DEFAULT_MEASURE_POLICIES.get(key))
        if not policy:
            continue
        prev_j = prev.judgments.get(key)
        if not prev_j:
            continue

        # Trends are computed on distance_from_preference (not raw measures),
        # so TARGET_BAND policies reflect movement toward/away from the band.
        val = judgment.distance_from_preference
        prev_val = prev_j.distance_from_preference
        if val is None or prev_val is None:
            continue

        trend = _trend_direction(val, prev_val, policy)
        if trend == Trend.UNKNOWN:
            continue

        judgment.trend = trend
        judgment.trend_delta = val - prev_val
        judgment.trend_confidence = 1.0


def assess_timeline(preferences: RiderPreferences, conditions: BikeConditions, *,
                    policies: dict[str, MeasurePolicy] | None = None) -> tuple[HourAssessment | None, list[HourAssessment]]:
    """
    Run assess_hour across current + forecast, enforcing consistent measure keys and chronological order.
    """
    current_assessment: HourAssessment | None = None
    hourly_assessments: list[HourAssessment] = []

    # Evaluate current conditions
    if conditions and conditions.current:
        current_assessment = assess_hour(preferences, conditions.current)

    # Evaluate forecast hours, skipping None entries
    hours = [h for h in (conditions.forecast or []) if h is not None]

    # Ensure chronological ordering by time then hour_index
    hours.sort(key=lambda h: (_get_field(h, "time"), _get_field(h, "hour_index") or 0))

    for h in hours:
        hourly_assessments.append(assess_hour(preferences, h))

    # Enforce consistent judgment keys across all assessments
    if hourly_assessments or current_assessment:
        key_source = (current_assessment or hourly_assessments[0]).judgments.keys()
        key_set = set(key_source)
        for a in hourly_assessments:
            missing = key_set - set(a.judgments.keys())
            for k in missing:
                a.judgments[k] = MeasureJudgment(status=Status.UNKNOWN, reasons=[])

    # Apply trends vs previous hour (forecast only)
    policy_map = policies or DEFAULT_MEASURE_POLICIES
    prev: HourAssessment | None = current_assessment
    for a in hourly_assessments:
        _apply_trends(a, prev, policy_map)
        prev = a

    return current_assessment, hourly_assessments


def _consecutive(hours: list[HourAssessment]) -> bool:
    """Return True if the list represents hourly consecutive timestamps."""
    if len(hours) < 2:
        return True

    for prev, curr in zip(hours, hours[1:]):
        delta = (curr.time - prev.time).total_seconds()
        if abs(delta - 3600) > 90:  # allow a small drift
            return False

    return True


def _aggregate_decision(hours: list[HourAssessment]) -> Decision:
    """Aggregate hour decisions to a window decision."""
    decisions = {h.decision for h in hours}
    if Decision.AVOID in decisions:
        return Decision.AVOID
    if Decision.GO_WITH_CAUTION in decisions:
        return Decision.GO_WITH_CAUTION
    if Decision.GO in decisions:
        return Decision.GO
    return Decision.UNKNOWN


def compute_window_recommendations(
    hourly: list[HourAssessment],
    *,
    durations_minutes: Sequence[int] = (45, 60, 90, 120),
) -> list[WindowRecommendation]:
    """
    Score contiguous windows and return recommendations for the best times to ride.

    - Windows containing any Decision.AVOID hour are skipped.
    - window_score is the average of included hour_scores.
    """
    if not hourly:
        return []

    # Normalize ordering so windows iterate in a chronological sequence.
    hourly_sorted = sorted(hourly, key=lambda h: h.time)
    recs: list[WindowRecommendation] = []

    # Slide a window start across the timeline and test each requested duration.
    for start_idx in range(len(hourly_sorted)):
        for duration in durations_minutes:
            # Convert minutes to whole-hour slots (ceil) and take the slice.
            needed_hours = ceil(duration / 60)
            slice_hours = hourly_sorted[start_idx : start_idx + needed_hours]
            if len(slice_hours) < needed_hours:
                continue
            # Skip non-contiguous hourly blocks.
            if not _consecutive(slice_hours):
                continue
            # Any hours marked as avoid makes the entire window ineligible.
            if any(h.decision == Decision.AVOID for h in slice_hours):
                continue

            # Aggregate window score/decision and collect risk evidence.
            window_score = sum((h.hour_score or 0.0) for h in slice_hours) / needed_hours
            decision = _aggregate_decision(slice_hours)
            risks = []
            for h in slice_hours:
                risks.extend(h.risks)
            reasons = [f"Average score {window_score:.1f} over {needed_hours} hour(s)"]

            # Emit a recommendation for this time span.
            recs.append(
                WindowRecommendation(
                    start=slice_hours[0].time,
                    end=slice_hours[-1].time,
                    duration=timedelta(minutes=duration),
                    decision=decision,
                    window_score=window_score,
                    reasons=reasons,
                    risks=risks,
                )
            )

    # Sort the best windows by score desc then earliest start
    recs.sort(key=lambda r: (-1 if r.window_score is None else -r.window_score, r.start))
    return recs


def _overall_decision(hours: list[HourAssessment]) -> Decision:
    """Compute the overall decision for a set of assessments."""
    decisions = {h.decision for h in hours}
    if Decision.AVOID in decisions:
        return Decision.AVOID
    if Decision.GO_WITH_CAUTION in decisions:
        return Decision.GO_WITH_CAUTION
    if Decision.GO in decisions:
        return Decision.GO
    return Decision.UNKNOWN


def _suitability_score(hours: list[HourAssessment]) -> float | None:
    """Compute the average suitability score across hours."""
    scored = [h.hour_score for h in hours if h.hour_score is not None]
    if not scored:
        return None
    return sum(scored) / len(scored)


def _dedupe_limit_flags(flags: list[RiskFlag], max_flags: int = 3) -> list[RiskFlag]:
    """Deduplicate and return the most important risk flags."""
    seen = set()
    unique: list[RiskFlag] = []
    for f in flags:
        key = (f.code, f.severity)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique[:max_flags]


def _primary_limiters(hours: list[HourAssessment], max_flags: int = 3) -> list[RiskFlag]:
    """Collect and deduplicate risks from hours."""
    flags: list[RiskFlag] = []
    for h in hours:
        flags.extend(h.risks)
    return _dedupe_limit_flags(flags, max_flags=max_flags)


def build_summary(hours: list[HourAssessment], windows: list[WindowRecommendation]) -> AssessmentSummary:
    """Build a summary object from assessments and window recommendations."""
    overall = _overall_decision(hours)
    score = _suitability_score(hours)
    best = windows[:3]
    if best:
        window_flags: list[RiskFlag] = []
        for w in best:
            window_flags.extend(w.risks)
        primary_limiters = _dedupe_limit_flags(window_flags)
    else:
        primary_limiters = _primary_limiters(hours)
    return AssessmentSummary(
        overall_decision=overall,
        suitability_score=score,
        primary_limiters=primary_limiters,
        best_windows=best,
    )
