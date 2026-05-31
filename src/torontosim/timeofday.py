"""Canonical time + calendar representation for the whole system.

ONE system so the frontend, the API, the simulator and the copilot can never
disagree on units:

  * time of day  — **minute-of-day**, integer ``0..1439`` (``MINUTES_PER_DAY``)
  * calendar day — **day-of-year**, ``1..365`` in a fixed simulated ``YEAR`` (2026)

Everything the simulator needs (``hour`` 0–23, ``day_of_week`` Mon=0..Sun=6,
``month`` 1–12, ``is_weekend``) is *derived* from those two via the helpers here
— callers never hand-roll the arithmetic. Transit GTFS times are seconds-of-day;
convert with :func:`seconds_to_minute_of_day`.

The mirror of this module on the frontend is ``frontend/src/lib/time.ts`` — keep
the two in lock-step (same YEAR, same conventions, especially weekday Mon=0).
"""

from __future__ import annotations

import datetime as _dt

#: Fixed simulated calendar year (2026 is non-leap → 365 days).
YEAR = 2026
MINUTES_PER_DAY = 1440
SECONDS_PER_DAY = 86_400
DAYS_IN_YEAR = 365


def clamp_minute_of_day(minute) -> int:
    """Coerce any numeric to a valid minute-of-day ``0..1439``."""
    try:
        m = int(round(float(minute)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(MINUTES_PER_DAY - 1, m))


def minute_of_day_to_hour(minute) -> int:
    """Hour-of-day ``0..23`` for a minute-of-day."""
    return clamp_minute_of_day(minute) // 60


def hhmm(minute) -> str:
    """``HH:MM`` label for a minute-of-day (e.g. 1020 -> ``'17:00'``)."""
    m = clamp_minute_of_day(minute)
    return f"{m // 60:02d}:{m % 60:02d}"


def seconds_to_minute_of_day(seconds) -> int:
    """Minute-of-day from a GTFS seconds-of-day value (wraps past midnight)."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return 0
    return (s // 60) % MINUTES_PER_DAY


def clamp_day_of_year(doy) -> int:
    """Coerce any numeric to a valid day-of-year ``1..365``."""
    try:
        d = int(round(float(doy)))
    except (TypeError, ValueError):
        return 1
    return max(1, min(DAYS_IN_YEAR, d))


def day_of_year_to_parts(doy) -> dict:
    """Calendar parts for a day-of-year in :data:`YEAR`.

    ``{"month": 1-12, "day": 1-31, "day_of_week": 0=Mon..6=Sun, "is_weekend": 0|1}``.
    Uses Python's ``date.weekday()`` (Mon=0), which is exactly the backend
    convention — so this is the single place the weekday numbering is decided.
    """
    d = _dt.date(YEAR, 1, 1) + _dt.timedelta(days=clamp_day_of_year(doy) - 1)
    dow = d.weekday()  # Mon=0 .. Sun=6
    return {"month": d.month, "day": d.day, "day_of_week": dow, "is_weekend": 1 if dow >= 5 else 0}
