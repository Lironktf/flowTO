"""P14 Phase 5 — confounders & matched controls tests (CPU pandas; runs on the GB10)."""

from __future__ import annotations

import pandas as pd

from torontosim.feedback.groundtruth.confounders import (
    aggregate_weather,
    flag_nearby_incidents,
    mark_confounder_dominated,
    select_matched_controls,
    survey_weather,
)


def _ts(s):
    return pd.Timestamp(s, tz="UTC")


def test_survey_weather_nearest_join_and_aggregate():
    during = pd.DataFrame(
        {
            "ID": ["r1", "r1"],
            "centreline_id": ["A", "A"],
            "dt": [_ts("2025-06-01T08:10:00"), _ts("2025-06-01T09:05:00")],
            "vol": [100, 120],
        }
    )
    weather = pd.DataFrame(
        {
            "dt": [_ts("2025-06-01T08:00:00"), _ts("2025-06-01T09:00:00")],
            "temp_c": [18.0, 20.0],
            "precip_mm": [0.0, 2.0],
            "snow": [0.0, 0.0],
            "visibility_km": [24.0, 10.0],
            "wind_kmh": [10.0, 15.0],
        }
    )
    dw = survey_weather(during, weather, tolerance_h=2)
    assert dw["temp_c"].tolist() == [18.0, 20.0]  # nearest hour each
    agg = aggregate_weather(dw).iloc[0]
    assert agg["temp_c"] == 19.0  # mean(18, 20)
    assert agg["visibility_km"] == 10.0  # min
    assert agg["precip_mm"] == 1.0  # mean(0, 2)


def _labels():
    return pd.DataFrame(
        {
            "ID": ["r1"],
            "centreline_id": ["A"],
            "site_lat": [43.6725],
            "site_lon": [-79.3849],
            "StartTime": [_ts("2025-06-01T00:00:00")],
            "EndTime": [_ts("2025-06-10T00:00:00")],
        }
    )


def test_incident_flag_spatial_and_temporal():
    incidents = pd.DataFrame(
        {
            "lat": [43.6726, 43.7000, 43.6726],  # near, far, near
            "lon": [-79.3849, -79.3000, -79.3849],
            "date": [_ts("2025-06-05"), _ts("2025-06-05"), _ts("2025-05-01")],  # in, in, before
        }
    )
    flagged = flag_nearby_incidents(_labels(), incidents, radius_m=200)
    assert flagged.loc[0, "incident_nearby"] == 1  # the near + in-window one
    dominated = mark_confounder_dominated(flagged)
    assert dominated.loc[0, "confounder_dominated"] == 1


def test_no_incident_when_far_or_out_of_window():
    incidents = pd.DataFrame(
        {"lat": [43.7000], "lon": [-79.3000], "date": [_ts("2025-06-05")]}  # far
    )
    flagged = flag_nearby_incidents(_labels(), incidents, radius_m=200)
    assert flagged.loc[0, "incident_nearby"] == 0
    assert mark_confounder_dominated(flagged).loc[0, "confounder_dominated"] == 0


def test_matched_controls_exclude_near_sites():
    restrictions = pd.DataFrame({"ID": ["r1"], "Latitude": [43.6725], "Longitude": [-79.3849]})
    sites = pd.DataFrame(
        {
            "centreline_id": ["near", "farA", "farB"],
            "site_lat": [43.6726, 43.80, 43.85],  # near is ~11 m; farA/farB are km away
            "site_lon": [-79.3849, -79.30, -79.25],
        }
    )
    controls = select_matched_controls(restrictions, sites, radius_m=500, n_controls=2)
    picked = set(controls["control_centreline_id"])
    assert "near" not in picked  # excluded (too close to the closure)
    assert picked == {"farA", "farB"}
