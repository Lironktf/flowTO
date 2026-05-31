"""P14 Phase 1 — spatial join tests (CPU pandas; runs on the GB10)."""

from __future__ import annotations

import pandas as pd

from torontosim.feedback.groundtruth.spatial import (
    bearing_deg,
    haversine_m,
    spatial_join,
    tmc_sites,
)

CLOSURE = (43.6725, -79.3849)


def test_haversine_known_distance():
    # ~11 m due north (one ten-thousandth degree lat ≈ 11.1 m)
    d = float(haversine_m(43.6725, -79.3849, 43.6726, -79.3849))
    assert 9.0 < d < 13.0


def test_bearing_quadrants():
    north = float(bearing_deg(*CLOSURE, 43.6735, -79.3849))  # due N
    east = float(bearing_deg(*CLOSURE, 43.6725, -79.3837))   # due E
    assert north < 5 or north > 355
    assert 85 < east < 95


def test_tmc_sites_collapses_to_centreline():
    tmc = pd.DataFrame(
        {
            "centreline_id": ["X", "X", "Y"],
            "latitude": [43.60, 43.62, 43.70],
            "longitude": [-79.40, -79.40, -79.30],
            "location_name": ["X st", "X st", "Y st"],
        }
    )
    sites = tmc_sites(tmc).sort_values("centreline_id").reset_index(drop=True)
    assert list(sites["centreline_id"]) == ["X", "Y"]
    assert sites.loc[0, "site_lat"] == 43.61  # mean of 43.60, 43.62


def _sites():
    return pd.DataFrame(
        {
            "centreline_id": ["A", "B", "C"],
            "site_lat": [43.6726, 43.6725, 43.7000],   # A ~11m N, B ~97m E, C far
            "site_lon": [-79.3849, -79.3837, -79.3000],
            "location_name": ["A int", "B int", "C int"],
        }
    )


def _restrictions():
    return pd.DataFrame(
        {
            "ID": ["r1"],
            "Road": ["Collier St"],
            "Name": ["work"],
            "Latitude": [CLOSURE[0]],
            "Longitude": [CLOSURE[1]],
        }
    )


def test_spatial_join_radius_and_keys():
    pairs = spatial_join(_sites(), _restrictions(), radius_m=500.0)
    # only A and B are within 500 m; C is excluded by the bbox/radius
    assert set(pairs["centreline_id"]) == {"A", "B"}
    assert (pairs["n_neighbour_sites"] == 2).all()
    a = pairs[pairs["centreline_id"] == "A"].iloc[0]
    b = pairs[pairs["centreline_id"] == "B"].iloc[0]
    assert 8 < a["dist_m"] < 15
    assert 80 < b["dist_m"] < 110
    # site key is centreline_id; closure coords renamed
    assert "closure_lat" in pairs and "closure_road" in pairs


def test_spatial_join_tighter_radius_excludes_far_site():
    pairs = spatial_join(_sites(), _restrictions(), radius_m=50.0)
    assert set(pairs["centreline_id"]) == {"A"}  # only the ~11 m site survives
