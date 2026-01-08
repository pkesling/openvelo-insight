import datetime as dt
from zoneinfo import ZoneInfo

from app.assessment_engine import compute_window_recommendations
from app.domain import Decision, HourAssessment, MeasureJudgment, Status


def _hour(ts: dt.datetime, score: float, decision: Decision = Decision.GO):
    return HourAssessment(
        time=ts,
        hour_index=0,
        decision=decision,
        judgments={"temperature_f": MeasureJudgment(status=Status.IDEAL)},
        risks=[],
        hour_score=score,
        notes=[],
    )


def test_windows_skip_avoid_hours_and_choose_best():
    tz = ZoneInfo("UTC")
    hours = [
        _hour(dt.datetime(2024, 1, 1, 12, tzinfo=tz), 8.0),
        _hour(dt.datetime(2024, 1, 1, 13, tzinfo=tz), 9.0),
        _hour(dt.datetime(2024, 1, 1, 14, tzinfo=tz), 2.0, decision=Decision.AVOID),
        _hour(dt.datetime(2024, 1, 1, 15, tzinfo=tz), 9.5),
    ]
    recs = compute_window_recommendations(hours, durations_minutes=(60, 120))
    # Avoid window should be skipped; best should start at 12 with avg (8+9)/2=8.5 or single 9?
    assert all(Decision.AVOID not in r.decision for r in recs)
    best = recs[0]
    assert best.start.hour == 13 or best.window_score >= 9.0


def test_windows_require_consecutive_hours():
    tz = ZoneInfo("UTC")
    h1 = _hour(dt.datetime(2024, 1, 1, 12, tzinfo=tz), 8.0)
    h2 = _hour(dt.datetime(2024, 1, 1, 14, tzinfo=tz), 9.0)  # gap
    recs = compute_window_recommendations([h1, h2], durations_minutes=(120,))
    assert recs == []
