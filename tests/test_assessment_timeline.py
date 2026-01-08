import datetime as dt
from zoneinfo import ZoneInfo

from app.assessment_engine import assess_timeline
from app.domain import RiderPreferences
from app.forecast_service import BikeConditions, BikeHourConditions


def _prefs():
    return RiderPreferences(
        preferred_temp_range_f=(65.0, 93.0),
        max_wind_mph=25.0,
        max_aqi=80,
        prefer_daylight=True,
        avoid_precip=True,
        avoid_poor_aqi=True,
        ride_window_hours=12,
    )


def _hour(idx: int, *, temp=70.0, aqi=None):
    tz = ZoneInfo("UTC")
    return BikeHourConditions(
        time=dt.datetime(2024, 1, 1, 12 + idx, 0, tzinfo=tz),
        hour_index=idx,
        temperature=temp,
        temperature_unit="°F",
        rel_humidity=50.0,
        rel_humidity_unit="%",
        dew_point=None,
        dew_point_unit=None,
        apparent_temperature=None,
        apparent_temperature_unit=None,
        precipitation_prob=10.0,
        precipitation_prob_unit="%",
        precipitation=0.0,
        precipitation_unit="mm",
        cloud_cover=20.0,
        cloud_cover_unit="%",
        wind_speed=5.0,
        wind_speed_unit="mph",
        wind_gusts=None,
        wind_gusts_unit=None,
        wind_direction=180.0,
        wind_direction_unit="deg",
        is_day=True,
        pm2_5=None,
        pm2_5_unit=None,
        pm10=None,
        pm10_unit=None,
        us_aqi=aqi,
        us_aqi_unit=None,
        ozone=None,
        ozone_unit=None,
        uv_index=None,
        uv_index_unit=None,
    )


def test_assess_timeline_orders_hours_chronologically():
    conditions = BikeConditions(
        current=_hour(0),
        forecast=[_hour(2), _hour(1)],
    )
    current, hourly = assess_timeline(_prefs(), conditions)
    assert current is not None
    assert [h.hour_index for h in hourly] == [1, 2]


def test_assess_timeline_skips_none_hours_and_keeps_keys():
    conditions = BikeConditions(
        current=_hour(0),
        forecast=[_hour(1), None, _hour(3, aqi=90.0)],
    )
    _, hourly = assess_timeline(_prefs(), conditions)
    assert len(hourly) == 2
    key_set = set(hourly[0].judgments.keys())
    for h in hourly:
        assert set(h.judgments.keys()) == key_set


def test_assess_timeline_trends_respect_deadband_and_directionality():
    prefs = _prefs()
    # temp within band, then cooler (distance increases) should be worsening
    conditions = BikeConditions(
        current=_hour(0, temp=70.0),
        forecast=[_hour(1, temp=60.0)],
    )
    _, hourly = assess_timeline(prefs, conditions)
    temp_j = hourly[0].judgments["temperature_f"]
    assert temp_j.trend == "worsening"
    assert temp_j.trend_delta is not None

    # wind_speed higher is worse -> lower is improving
    conditions = BikeConditions(
        current=_hour(0, temp=70.0),
        forecast=[_hour(1, temp=70.0, aqi=20.0)],
    )
    _, hourly = assess_timeline(prefs, conditions)
    wind_j = hourly[0].judgments["wind_speed_mph"]
    assert wind_j.trend is not None
