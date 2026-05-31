"""P14 Phase 3 — baseline + signed labels tests (CPU pandas; runs on the GB10)."""

from __future__ import annotations

import pandas as pd

from torontosim.feedback.groundtruth.labels import build_labels


def _during_slots():
    # the (hour, dow) slots observed during each window, per (ID, centreline_id)
    return pd.DataFrame(
        {
            "ID": ["r1", "r2", "r3", "r4"],
            "centreline_id": ["A", "B", "C", "D"],
            "hour": [8, 9, 7, 10],
            "dow": [2, 3, 1, 4],
        }
    )


def _pre():
    rows = [
        # r1/A: Tier-1 (hour=8,dow=2) baseline mean 200
        ("r1", "A", 8, 2, 160, 1), ("r1", "A", 8, 2, 240, 2),
        # r2/B: baseline mean 200, tight std → a +100 rise is significant
        ("r2", "B", 9, 3, 180, 3), ("r2", "B", 9, 3, 220, 4),
        # r3/C: no pre survey at all → no baseline
        # r4/D: only hour=10 matches (dow=5 ≠ 4) → Tier-2 (hour) baseline mean 160
        ("r4", "D", 10, 5, 150, 5), ("r4", "D", 10, 5, 170, 6),
    ]
    df = pd.DataFrame(rows, columns=["ID", "centreline_id", "hour", "dow", "vol", "count_id"])
    df["cars"], df["trucks"], df["buses"] = df["vol"], 0, 0
    return df


def _during_agg():
    return pd.DataFrame(
        {
            "ID": ["r1", "r2", "r3", "r4"],
            "centreline_id": ["A", "B", "C", "D"],
            "during_vol_mean": [150.0, 300.0, 120.0, 100.0],
        }
    )


def _labels():
    return build_labels(_during_agg(), _during_slots(), _pre()).set_index("ID")


def test_tier1_signed_drop():
    a = _labels().loc["r1"]
    assert a["has_baseline"] == 1 and a["baseline_match"] == "hour_dow"
    assert a["vol_delta"] == -50.0 and a["vol_delta_pct"] == -25.0
    assert a["direction"] == 0 and a["significant"] == 0  # a drop, not significant


def test_significant_rise():
    b = _labels().loc["r2"]
    assert b["vol_delta"] == 100.0
    assert b["direction"] == 1 and b["significant"] == 1


def test_no_baseline_is_null_not_zero():
    c = _labels().loc["r3"]
    assert c["has_baseline"] == 0 and c["baseline_match"] == "none"
    assert pd.isna(c["vol_delta"]) and pd.isna(c["direction"])


def test_tier2_hour_fallback():
    d = _labels().loc["r4"]
    assert d["has_baseline"] == 1 and d["baseline_match"] == "hour"
    assert d["vol_delta"] == -60.0  # 100 - 160
