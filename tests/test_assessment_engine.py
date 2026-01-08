import datetime as dt

import pytest

from app.assessment_engine import assess_hour
from app.domain import Decision, RiderPreferences, RiskCode, RiskSeverity, Status


def prefs():
    return RiderPreferences(
        preferred_temp_range_f=(65.0, 93.0),
        max_wind_mph=25.0,
        max_aqi=80,
        prefer_daylight=True,
        avoid_precip=True,
        avoid_poor_aqi=True,
        ride_window_hours=12,
    )


def make_hour(**overrides):
    base = {
        "time": dt.datetime(2025, 1, 1, 12, 0),
        "hour_index": 0,
        "temperature": 70.0,
        "wind_speed": 10.0,
        "wind_gusts": 15.0,
        "us_aqi": 30,
        "precipitation_prob": 10.0,
        "is_day": True,
    }
    base.update(overrides)
    return base


def test_assess_hour_extreme_cold_triggers_avoid():
    result = assess_hour(prefs(), make_hour(temperature=25.0))
    assert result.decision == Decision.AVOID
    assert result.judgments["temperature_f"].status == Status.AVOID
    assert any(r.code == RiskCode.EXTREME_COLD for r in result.risks)


def test_assess_hour_near_freezing_is_caution():
    result = assess_hour(prefs(), make_hour(temperature=33.0))
    assert result.judgments["temperature_f"].status == Status.CAUTION
    assert result.decision == Decision.GO_WITH_CAUTION
    cold_risk = next(r for r in result.risks if r.code == RiskCode.EXTREME_COLD)
    assert cold_risk.severity in {RiskSeverity.MODERATE, RiskSeverity.MAJOR}


def test_aqi_good_and_at_limit():
    res_good = assess_hour(prefs(), make_hour(us_aqi=30))
    assert res_good.judgments["us_aqi"].status == Status.IDEAL
    res_limit = assess_hour(prefs(), make_hour(us_aqi=80))
    assert res_limit.judgments["us_aqi"].status == Status.ACCEPTABLE
    assert all(r.code != RiskCode.POOR_AIR_QUALITY for r in res_limit.risks)


def test_wind_and_gust_thresholds():
    res_windy = assess_hour(prefs(), make_hour(wind_speed=26.0))
    assert res_windy.judgments["wind_speed_mph"].status == Status.CAUTION
    assert any(r.code == RiskCode.HIGH_WIND for r in res_windy.risks)

    res_gusty = assess_hour(prefs(), make_hour(wind_gusts=42.0, wind_speed=10.0))
    assert res_gusty.judgments["wind_gusts_mph"].status in {Status.CAUTION, Status.AVOID}
    assert any(r.code == RiskCode.GUSTY_WIND for r in res_gusty.risks)


def test_missing_values_become_unknown():
    hour = make_hour(us_aqi=None, wind_speed=None, wind_gusts=None, precipitation_prob=None)
    res = assess_hour(prefs(), hour)
    assert res.judgments["us_aqi"].status == Status.UNKNOWN
    assert res.judgments["wind_speed_mph"].status == Status.UNKNOWN
    assert res.judgments["precipitation_prob_percent"].status == Status.UNKNOWN
    assert res.decision in {Decision.GO, Decision.UNKNOWN}
