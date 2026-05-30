"""P02 Centreline loader unit tests: oneway, dedupe, filtering, calibration."""

from __future__ import annotations

from torontosim.graph import calibrate_capacity
from torontosim.graph.centreline_loader import (
    _oneway_direction,
    build_centreline_graph,
    build_nodes,
)

INTERSECTIONS = [
    {"INTERSECTION_ID": 10, "longitude": -79.40, "latitude": 43.64},
    {"INTERSECTION_ID": 20, "longitude": -79.39, "latitude": 43.64},
    {"INTERSECTION_ID": 20, "longitude": -79.39, "latitude": 43.64},  # dup
]


def test_build_nodes_dedupes_and_reads_latlon_columns():
    nodes = build_nodes(INTERSECTIONS)
    assert set(nodes) == {10, 20}
    assert nodes[10] == (-79.40, 43.64)  # (lon, lat)


def test_oneway_direction_codes():
    assert _oneway_direction({"ONEWAY_DIR_CODE": 0}) == 0
    assert _oneway_direction({"ONEWAY_DIR_CODE": 1}) == 1
    assert _oneway_direction({"ONEWAY_DIR_CODE": -1}) == -1
    assert _oneway_direction({}) == 0  # missing -> two-way default


def test_oneway_against_digitized_reverses_edge():
    tcl = [
        {
            "CENTRELINE_ID": 5,
            "FROM_INTERSECTION_ID": 10,
            "TO_INTERSECTION_ID": 20,
            "ONEWAY_DIR_CODE": -1,  # one-way against digitization -> 20->10 only
            "FEATURE_CODE_DESC": "Local",
        }
    ]
    g = build_centreline_graph(tcl, INTERSECTIONS)
    assert g.has_edge(20, 10)
    assert not g.has_edge(10, 20)


def test_calibration_raises_capacity_on_tmc_match():
    tcl = [
        {
            "CENTRELINE_ID": 777,
            "FROM_INTERSECTION_ID": 10,
            "TO_INTERSECTION_ID": 20,
            "ONEWAY_DIR_CODE": 1,
            "FEATURE_CODE_DESC": "Local",  # residential default cap is small
        }
    ]
    g = build_centreline_graph(tcl, INTERSECTIONS)
    edge = next(iter(g.edges(data=True)))[2]
    base_cap = edge["capacity"]

    # Observed peak far above the modeled residential capacity.
    tmc = [{"centreline_id": 777, "veh_15min": 1000}]  # *4 = 4000 veh/hr peak
    n = calibrate_capacity.calibrate(g, tmc)
    assert n == 1
    edge = next(iter(g.edges(data=True)))[2]
    assert edge["capacity"] > base_cap
    assert edge["confidence"]["capacity"] == "observed"
