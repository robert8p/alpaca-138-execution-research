from datetime import date, timezone

from app.timeutils import decision_timestamp, time_exit_timestamp


def test_london_decision_respects_uk_dst():
    assert decision_timestamp(date(2025, 1, 15)).hour == 17
    assert decision_timestamp(date(2025, 7, 15)).hour == 16
    assert decision_timestamp(date(2025, 7, 15)).tzinfo == timezone.utc


def test_us_uk_dst_mismatch_is_not_hardcoded_to_noon_et():
    # US daylight saving begins before UK daylight saving in March.
    ts = decision_timestamp(date(2025, 3, 20))
    assert ts.hour == 17
    assert int(ts.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).hour) == 13


def test_time_exit_is_always_1555_new_york():
    from zoneinfo import ZoneInfo
    for day in (date(2025, 1, 15), date(2025, 7, 15)):
        assert time_exit_timestamp(day).astimezone(ZoneInfo("America/New_York")).strftime("%H:%M") == "15:55"
