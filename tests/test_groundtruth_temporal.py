"""P14 Phase 2 — temporal/during aggregation tests (CPU pandas; runs on the GB10)."""

from __future__ import annotations

import pandas as pd

from torontosim.feedback.groundtruth.temporal import during_aggregate, tmc_observations


def test_tmc_observations_class_and_direction_sums():
    raw = pd.DataFrame(
        {
            "centreline_id": ["A"],
            "count_id": [1],
            "start_time": ["2025-06-01T08:00:00"],
            "n_appr_cars_t": [10],
            "s_appr_truck_t": [2],
            "n_appr_bus_l": [1],
        }
    )
    obs = tmc_observations(raw)
    r = obs.iloc[0]
    assert r["vol"] == 13 and r["cars"] == 10 and r["trucks"] == 2 and r["buses"] == 1
    assert r["dir_n"] == 11 and r["dir_s"] == 2  # n: cars10+bus1 ; s: truck2
    assert r["hour"] == 8


def _raw_for_window():
    return pd.DataFrame(
        {
            "centreline_id": ["A", "A", "A", "A", "B"],
            "count_id": [1, 2, 3, 4, 5],
            "start_time": [
                "2025-06-01T00:00:00",  # == StartTime → included
                "2025-06-05T00:00:00",  # inside → included
                "2025-06-10T00:00:00",  # == EndTime → EXCLUDED (half-open)
                "2025-05-30T00:00:00",  # before → excluded
                "2025-05-01T00:00:00",  # site B, before → no during row
            ],
            "n_appr_cars_t": [100, 200, 999, 50, 10],
        }
    )


def _pairs():
    return pd.DataFrame(
        {
            "ID": ["r1", "r1"],
            "centreline_id": ["A", "B"],
            "StartTime": [pd.Timestamp("2025-06-01T00:00:00Z")] * 2,
            "EndTime": [pd.Timestamp("2025-06-10T00:00:00Z")] * 2,
        }
    )


def test_during_window_boundaries_and_no_fabrication():
    obs = tmc_observations(_raw_for_window())
    agg = during_aggregate(_pairs(), obs)
    # only site A has in-window surveys; B has none → no row (no fabrication)
    assert list(agg["centreline_id"]) == ["A"]
    a = agg.iloc[0]
    assert a["obs_during"] == 2              # start included, end excluded
    assert a["survey_days_during"] == 2      # distinct count_ids
    assert a["during_vol_mean"] == 150.0     # mean(100, 200)


def test_during_empty_when_no_overlap():
    obs = tmc_observations(_raw_for_window())
    pairs = _pairs().assign(
        StartTime=pd.Timestamp("2030-01-01T00:00:00Z"),
        EndTime=pd.Timestamp("2030-02-01T00:00:00Z"),
    )
    agg = during_aggregate(pairs, obs)
    assert agg.empty
