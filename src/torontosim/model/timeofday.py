"""Time-of-day factoring: daily OD -> AM/PM peak-hour OD (P03).

Peak-hour shares follow typical GTA travel-survey bands (TTS time bands; ~9% of
daily trips in the AM peak hour, ~10% in the PM peak hour). AM peak skews
inbound (toward downtown), PM outbound — callers can apply directional bias via
``inbound_share`` when they have a downtown reference.
"""

from __future__ import annotations

from collections.abc import Mapping

# Peak-hour share of daily trips, and inbound (toward-downtown) fraction.
PEAK_FACTORS = {
    "am": {"share": 0.09, "inbound": 0.65},
    "pm": {"share": 0.10, "inbound": 0.35},
    "midday": {"share": 0.06, "inbound": 0.50},
    "offpeak": {"share": 0.03, "inbound": 0.50},
}


def peak_hour_share(period: str) -> float:
    """Fraction of daily trips occurring in the given period's peak hour."""
    return PEAK_FACTORS.get(period, PEAK_FACTORS["offpeak"])["share"]


def inbound_share(period: str) -> float:
    return PEAK_FACTORS.get(period, PEAK_FACTORS["offpeak"])["inbound"]


def factor_daily_to_peak(daily_od: Mapping, period: str) -> dict:
    """Scale a daily OD dict to the period's peak-hour volume (uniform scale).

    Directional biasing is left to the caller (needs a downtown reference);
    this preserves the OD shape and total share deterministically.
    """
    share = peak_hour_share(period)
    return {k: float(v) * share for k, v in daily_od.items()}
