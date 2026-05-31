"""P14 Phase 4 — openings tests (CPU pandas; runs on the GB10)."""

from __future__ import annotations

import pandas as pd

from torontosim.feedback.groundtruth.openings import (
    build_opening_labels,
    split_after,
)


def _ts(s):
    return pd.Timestamp(s, tz="UTC")


def _obs(rows):
    # rows: (centreline_id, count_id, dt_str, vol)
    df = pd.DataFrame(rows, columns=["centreline_id", "count_id", "dt", "vol"])
    df["dt"] = pd.to_datetime(df["dt"], utc=True)
    df["hour"] = df["dt"].dt.hour
    df["dow"] = df["dt"].dt.dayofweek
    df["cars"], df["trucks"], df["buses"] = df["vol"], 0, 0
    return df


def _pairs():
    return pd.DataFrame(
        {
            "ID": ["r1"],
            "centreline_id": ["A"],
            "StartTime": [_ts("2025-06-01T00:00:00")],
            "EndTime": [_ts("2025-06-10T00:00:00")],  # dur 9d → after window [06-10, 06-19)
        }
    )


def test_split_after_window_and_boundaries():
    obs = _obs(
        [
            ("A", 1, "2025-06-10T00:00:00", 180),  # == EndTime → included
            ("A", 2, "2025-06-15T00:00:00", 200),  # inside → included
            ("A", 3, "2025-06-25T00:00:00", 999),  # past 06-19 cap → excluded
            ("A", 4, "2025-06-05T00:00:00", 100),  # during closure → excluded
        ]
    )
    after = split_after(_pairs(), obs, cap_days=90)
    assert sorted(after["count_id"]) == [1, 2]


def test_split_after_respects_cap_days():
    obs = _obs([("A", 1, "2025-06-12T00:00:00", 180)])  # 2 days after EndTime
    # cap_days=1 → after window is only [06-10, 06-11) → the 06-12 survey is excluded
    assert split_after(_pairs(), obs, cap_days=1).empty


def test_opening_label_recovery_is_positive():
    after_agg = pd.DataFrame({"ID": ["r1"], "centreline_id": ["A"], "after_vol_mean": [180.0]})
    after = pd.DataFrame({"ID": ["r1"], "centreline_id": ["A"], "hour": [8], "dow": [2]})
    during = pd.DataFrame(
        {
            "ID": ["r1", "r1"],
            "centreline_id": ["A", "A"],
            "hour": [8, 8],
            "dow": [2, 2],
            "vol": [100, 120],  # during-closure baseline mean 110
            "count_id": [1, 2],
            "cars": [100, 120],
            "trucks": [0, 0],
            "buses": [0, 0],
        }
    )
    lab = build_opening_labels(after_agg, after, during).iloc[0]
    assert lab["intervention_sign"] == "opening"
    assert lab["has_baseline"] == 1
    assert lab["vol_delta"] == 70.0  # 180 - 110
    assert lab["direction"] == 1  # more traffic after reopening
