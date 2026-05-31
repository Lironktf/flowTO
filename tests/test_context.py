"""Tests for the shared residual-GNN context builder (torch-free + parity)."""

from __future__ import annotations

import numpy as np
import pytest

from torontosim.feedback.context import (
    CONTEXT_DIM,
    CONTEXT_FEATURE_NAMES,
    context_features,
    scenario_context,
)


def test_dim_and_names():
    assert CONTEXT_DIM == 14 == len(CONTEXT_FEATURE_NAMES)
    assert scenario_context(None).shape == (14,)
    assert scenario_context(None).dtype == np.float32


def test_time_and_weather_signals():
    v = context_features({"hour": 8, "day_of_week": 1, "month": 1, "weather": "snow"})
    assert v[4] == 1.0  # 8am = rush hour
    assert v[3] == 0.0  # Tue = not weekend
    assert (v[5], v[6], v[7]) == (0.0, 0.0, 1.0)  # snow, not clear/rain
    assert v[10] == 1.0  # Jan = winter one-hot
    # a partial/empty context still yields a valid, finite vector
    assert np.all(np.isfinite(scenario_context({})))


def test_weekend_and_weather_buckets():
    assert context_features({"day_of_week": 6})[3] == 1.0  # Sun = weekend
    assert context_features({"weather": "rain"})[6] == 1.0
    assert context_features({"weather": "clear"})[5] == 1.0


def test_parity_with_baseline_when_torch_present():
    """feedback.context must match models.gnn.utils.context_vector (no drift)."""
    pytest.importorskip("torch")
    from models.gnn.utils import context_vector

    for tc in (
        None,
        {"hour": 8, "day_of_week": 1, "month": 1, "weather": "snow"},
        {"hour": 17, "weather": "rain", "temperature_c": 5.0, "precipitation_mm": 12.0},
        {"day_of_week": 6, "month": 7, "weather": "clear"},
    ):
        assert context_features(tc) == pytest.approx(context_vector(tc))
