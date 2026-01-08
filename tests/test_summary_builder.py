import datetime as dt
from zoneinfo import ZoneInfo

from app.assessment_engine import build_summary
from app.domain import AssessmentSummary, Decision, HourAssessment, MeasureJudgment, RiskFlag, RiskSeverity, Status, WindowRecommendation


def _hour(decision: Decision, score: float, risks=None):
    return HourAssessment(
        time=dt.datetime(2024, 1, 1, 12, tzinfo=ZoneInfo("UTC")),
        hour_index=0,
        decision=decision,
        judgments={"temperature_f": MeasureJudgment(status=Status.IDEAL)},
        risks=risks or [],
        hour_score=score,
        notes=[],
    )


def _window(score: float):
    now = dt.datetime(2024, 1, 1, 12, tzinfo=ZoneInfo("UTC"))
    return WindowRecommendation(
        start=now,
        end=now,
        duration=None,
        decision=Decision.GO,
        window_score=score,
        reasons=[],
        risks=[],
    )


def test_summary_aggregates_score_and_decision():
    hours = [
        _hour(Decision.GO, 8.0),
        _hour(Decision.GO_WITH_CAUTION, 6.0),
    ]
    windows = [_window(8.0)]
    summary = build_summary(hours, windows)
    assert isinstance(summary, AssessmentSummary)
    assert summary.overall_decision == Decision.GO_WITH_CAUTION
    assert summary.suitability_score == 7.0
    assert summary.best_windows


def test_primary_limiters_deduplicates():
    risk = RiskFlag(code="high_wind", severity=RiskSeverity.MODERATE, evidence=[])
    hours = [_hour(Decision.GO, 9.0, risks=[risk, risk])]
    windows = []
    summary = build_summary(hours, windows)
    assert len(summary.primary_limiters) == 1


def test_primary_limiters_prefer_window_risks():
    darkness = RiskFlag(code="darkness", severity=RiskSeverity.MINOR, evidence=[])
    hours = [_hour(Decision.GO, 9.0, risks=[darkness])]
    window = _window(8.0)
    summary = build_summary(hours, [window])
    assert summary.primary_limiters == []
