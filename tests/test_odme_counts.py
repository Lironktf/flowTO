"""W3 — ODME against TMC counts wired into OD construction.

``generate_od_matrix(calibration="ipf_counts", tmc_records=…)`` should reconcile
the gravity OD's *assigned* link flows toward the observed TMC peak counts
(keyed on ``centreline_id``), deterministically, while ``calibration="none"``
stays the demo-safe gravity baseline.
"""

from __future__ import annotations

from torontosim.graph.calibrate_capacity import observed_peak_by_centreline
from torontosim.graph.centreline_loader import build_centreline_graph
from torontosim.model.generate_od_matrix import (
    assigned_counts_by_centreline,
    generate_od_matrix,
)
from torontosim.model.odme import total_abs_error

# A 3-node arterial corridor, nodes ~0.8 km apart so OD pairs clear MIN_TRIP_KM.
INTERSECTIONS = [
    {"INTERSECTION_ID": 1, "geometry": {"type": "Point", "coordinates": [-79.40, 43.64]}},
    {"INTERSECTION_ID": 2, "geometry": {"type": "Point", "coordinates": [-79.39, 43.64]}},
    {"INTERSECTION_ID": 3, "geometry": {"type": "Point", "coordinates": [-79.38, 43.64]}},
]
TCL = [
    {
        "CENTRELINE_ID": 111,
        "LINEAR_NAME_FULL": "West Link",
        "FROM_INTERSECTION_ID": 1,
        "TO_INTERSECTION_ID": 2,
        "ONEWAY_DIR_CODE": 0,
        "FEATURE_CODE_DESC": "Major Arterial",
    },
    {
        "CENTRELINE_ID": 222,
        "LINEAR_NAME_FULL": "East Link",
        "FROM_INTERSECTION_ID": 2,
        "TO_INTERSECTION_ID": 3,
        "ONEWAY_DIR_CODE": 0,
        "FEATURE_CODE_DESC": "Major Arterial",
    },
]

# Mid-day weekday: no commute biasing -> symmetric, deterministic strengths.
TC = {"hour": 12, "day_of_week": 2, "month": 6, "weather": "clear"}
DEMAND = {1: 100.0, 2: 100.0, 3: 100.0}

# Observed TMC peaks the gravity OD does NOT already match.
TMC = [
    {"centreline_id": 111, "veh_15min": 500},  # *4 -> 2000 veh/hr peak
    {"centreline_id": 222, "veh_15min": 100},  # *4 -> 400 veh/hr peak
]


def _graph():
    return build_centreline_graph(TCL, INTERSECTIONS)


def test_ipf_counts_tracks_tmc_better_than_gravity():
    graph = _graph()
    observed = observed_peak_by_centreline(TMC)
    assert set(observed) == {111, 222}

    od_none = generate_od_matrix(graph, DEMAND, TC, calibration="none")
    od_cal = generate_od_matrix(graph, DEMAND, TC, calibration="ipf_counts", tmc_records=TMC)
    assert od_none and od_cal

    err_none = total_abs_error(assigned_counts_by_centreline(od_none, graph), observed)
    err_cal = total_abs_error(assigned_counts_by_centreline(od_cal, graph), observed)
    # ODME drives the assigned link flows toward the observed counts.
    assert err_cal < err_none


def test_ipf_counts_is_deterministic():
    graph = _graph()
    a = generate_od_matrix(graph, DEMAND, TC, calibration="ipf_counts", tmc_records=TMC)
    b = generate_od_matrix(graph, DEMAND, TC, calibration="ipf_counts", tmc_records=TMC)
    assert a == b


def test_ipf_counts_without_records_falls_back_to_ipf():
    graph = _graph()
    # No tmc_records -> must not raise; degrades to the Furness-balanced OD.
    od = generate_od_matrix(graph, DEMAND, TC, calibration="ipf_counts")
    od_ipf = generate_od_matrix(graph, DEMAND, TC, calibration="ipf")
    assert od == od_ipf


def test_default_calibration_none_unchanged():
    graph = _graph()
    a = generate_od_matrix(graph, DEMAND, TC)  # default
    b = generate_od_matrix(graph, DEMAND, TC, calibration="none")
    assert a == b
    # Default never routes/ODMEs, so passing tmc_records has no effect.
    c = generate_od_matrix(graph, DEMAND, TC, tmc_records=TMC)
    assert a == c
