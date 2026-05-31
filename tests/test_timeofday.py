"""Canonical time-of-day system: conversions + normalize_time_context wiring."""

from __future__ import annotations

from torontosim import timeofday as t
from torontosim.model.features import normalize_time_context


def test_minute_of_day_conversions():
    assert t.clamp_minute_of_day(-5) == 0
    assert t.clamp_minute_of_day(5000) == 1439  # clamp, never wrap
    assert t.clamp_minute_of_day(1020) == 1020
    assert t.minute_of_day_to_hour(1020) == 17
    assert t.minute_of_day_to_hour(0) == 0
    assert t.hhmm(1020) == "17:00"
    assert t.hhmm(0) == "00:00"
    assert t.hhmm(870) == "14:30"


def test_seconds_to_minute_of_day():
    assert t.seconds_to_minute_of_day(14 * 3600) == 14 * 60  # GTFS 14:00:00 → 840
    assert t.seconds_to_minute_of_day(0) == 0


def test_day_of_year_parts_weekday_is_monday_zero():
    # 2026-01-01 is a Thursday → Mon=0 convention makes it 3.
    p = t.day_of_year_to_parts(1)
    assert p["month"] == 1 and p["day"] == 1
    assert p["day_of_week"] == 3  # Thursday
    assert p["is_weekend"] == 0
    # 2026-06-12 is a Friday (the demo default day-of-year 163).
    p2 = t.day_of_year_to_parts(163)
    assert (p2["month"], p2["day"]) == (6, 12)
    assert p2["day_of_week"] == 4 and p2["is_weekend"] == 0


def test_day_of_year_weekend_detection():
    # 2026-06-13 is a Saturday → day-of-year 164.
    p = t.day_of_year_to_parts(164)
    assert p["day_of_week"] == 5 and p["is_weekend"] == 1


def test_normalize_derives_hour_from_minute():
    out = normalize_time_context({"minute": 480})
    assert out["hour"] == 8  # 08:00
    assert out["minute"] == 480


def test_normalize_derives_calendar_from_day_of_year():
    out = normalize_time_context({"minute": 1020, "day_of_year": 164})
    assert out["hour"] == 17
    assert out["month"] == 6
    assert out["day_of_week"] == 5  # Saturday, Mon=0
    assert out["is_weekend"] == 1
    assert out["season"] == "summer"


def test_normalize_day_of_year_overrides_carried_forward_date():
    # retime merges {old normalized tc} with {new minute/day_of_year}; the new
    # day_of_year must WIN over the stale month/day_of_week/season, else re-timing
    # to a new date silently keeps the old weekday/season.
    stale = {"hour": 17, "day_of_week": 4, "month": 6, "season": "summer", "is_weekend": 0}
    out = normalize_time_context({**stale, "minute": 480, "day_of_year": 1})  # Jan 1 (Thu)
    assert out["hour"] == 8
    assert out["month"] == 1
    assert out["day_of_week"] == 3  # Thursday, not the stale Friday(4)
    assert out["season"] == "winter"  # not the stale summer


def test_normalize_explicit_fields_still_work():
    # Back-compat: callers passing hour/day_of_week directly are unaffected.
    out = normalize_time_context({"hour": 9, "day_of_week": 6})
    assert out["hour"] == 9
    assert out["is_weekend"] == 1
