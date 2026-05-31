"""Shared, torch-free context-feature builder for the residual closure GNN (P13 enrichment).

The model's per-scenario context channel — time-of-day + weather now, events/incidents
and multimodal later — is built HERE so training (``dataset.build_stage2_tensors``) and
inference (``api/residual_edit.py``) stay in lockstep: enrich the channels in one place
and both the model and the integration upgrade together, with no caller changes.

It mirrors the baseline GNN's 14-feature context contract
(``models/gnn/utils.py:context_vector``) — ``hour/dow/month/weekend/rush`` ·
``weather clear/rain/snow`` · ``temp_c/precip_mm`` · ``season`` — but is reimplemented
torch-free (the baseline module imports torch, which must not leak into the inference
path or CI). ``test_context.py`` asserts parity with the baseline so the two can't drift.
A scenario's context is one row, broadcast across all edges. See
``docs/specs/13-feedback-loop.md`` §C (Context channels).
"""

from __future__ import annotations

import numpy as np

CONTEXT_FEATURE_NAMES = [
    "hour_norm",
    "day_of_week_norm",
    "month_norm",
    "is_weekend",
    "rush_hour",
    "weather_clear",
    "weather_rain",
    "weather_snow",
    "temperature_c_norm",
    "precipitation_mm_norm",
    "season_winter",
    "season_spring",
    "season_summer",
    "season_fall",
]
CONTEXT_DIM = len(CONTEXT_FEATURE_NAMES)


def _safe_float(value, default: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if f == f else default  # reject NaN


def _is_rush_hour(hour: int) -> int:
    return int(hour in (7, 8, 9, 16, 17, 18, 19))


def _season_one_hot(month: int) -> list[float]:
    if month in (12, 1, 2):
        return [1.0, 0.0, 0.0, 0.0]
    if month in (3, 4, 5):
        return [0.0, 1.0, 0.0, 0.0]
    if month in (6, 7, 8):
        return [0.0, 0.0, 1.0, 0.0]
    return [0.0, 0.0, 0.0, 1.0]


def context_features(time_context: dict | None = None) -> list[float]:
    """The 14 context features for one scenario's time/weather (torch-free).

    ``None`` / missing keys fall back to the normalized defaults (weekday PM peak, clear),
    so a caller can pass a partial context and still get a valid vector.
    """
    tc = dict(time_context or {})
    hour = int(tc.get("hour", 17))
    dow = int(tc.get("day_of_week", 4))
    month = int(tc.get("month", 6))
    is_weekend = int(tc.get("is_weekend", 1 if dow >= 5 else 0))
    weather = str(tc.get("weather") or "clear").lower()
    temp = _safe_float(tc.get("temperature_c"), 18.0)
    precip = _safe_float(tc.get("precipitation_mm"), 0.0)
    return [
        hour / 23.0,
        dow / 6.0,
        month / 12.0,
        float(is_weekend),
        float(_is_rush_hour(hour)),
        float(weather in ("clear", "cloud", "cloudy", "overcast")),
        float(weather in ("rain", "fog", "drizzle")),
        float(weather == "snow"),
        temp / 40.0,
        min(precip, 50.0) / 50.0,
        *_season_one_hot(month),
    ]


def scenario_context(time_context: dict | None = None) -> np.ndarray:
    """``context_features`` as a float32 ``[CONTEXT_DIM]`` array (the model input row)."""
    return np.asarray(context_features(time_context), dtype=np.float32)
