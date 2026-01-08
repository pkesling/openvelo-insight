import datetime as dt
import json
import pytest
from zoneinfo import ZoneInfo

from app.domain import AgentAssessmentPayload, AssessmentContext, AssessmentSummary, Decision, HourAssessment, MeasureJudgment, RiderPreferences, Status, WindowRecommendation
from app.narration import build_narration_messages, validate_narration_output


def _payload():
    now = dt.datetime(2024, 1, 1, 12, tzinfo=ZoneInfo("UTC"))
    return AgentAssessmentPayload(
        context=AssessmentContext(generated_at=now),
        preferences=RiderPreferences(),
        summary=AssessmentSummary(
            overall_decision=Decision.GO,
            suitability_score=8.0,
            primary_limiters=[],
            best_windows=[
                WindowRecommendation(
                    start=now,
                    end=now,
                    duration=None,
                    decision=Decision.GO,
                    window_score=8.0,
                    reasons=[],
                    risks=[],
                )
            ],
        ),
        current=None,
        hourly=[
            HourAssessment(
                time=now,
                hour_index=0,
                decision=Decision.GO,
                judgments={"temperature_f": MeasureJudgment(status=Status.IDEAL)},
                risks=[],
                hour_score=8.0,
                notes=[],
            )
        ],
        policies={},
    )


def test_build_messages_includes_summary_and_windows():
    payload = _payload()
    msgs = build_narration_messages(payload)
    assert msgs[0]["role"] == "system"
    content = msgs[1]["content"]
    assert "Suitability score: 8.0" in content
    assert "Best windows" in content


def test_validate_narration_output_passes_and_rejects_mismatch():
    payload = _payload()
    raw = "Suitability score 8.0. Looks good."
    assert validate_narration_output(raw, payload.summary.suitability_score) is not None

    bad_raw = "Suitability score 5.0. Looks good overall"
    with pytest.raises(ValueError):
        validate_narration_output(bad_raw, payload.summary.suitability_score)
