"""Measured-baseline (raw TMC → per-edge congestion, no ML) unit tests."""

from __future__ import annotations

import networkx as nx

from torontosim.datapipeline.tmc_baseline import (
    _civil_dow,
    _classify_side,
    aggregate_tmc,
    build_baseline_model,
)

_HEADER = "count_id,count_date,start_time,latitude,longitude,n_appr_cars_t,s_appr_cars_t\n"


def test_civil_dow_monday_zero():
    assert _civil_dow(2026, 6, 10) == 2  # Wed
    assert _civil_dow(2026, 6, 12) == 4  # Fri
    assert _civil_dow(2020, 3, 10) == 1  # Tue


def test_classify_side_by_neighbour_offset():
    # neighbour north of the node → vehicles arrive from the north (n_appr)
    assert _classify_side(0.01, 0.0) == "n_appr"
    assert _classify_side(-0.01, 0.0) == "s_appr"
    assert _classify_side(0.0, 0.01) == "e_appr"
    assert _classify_side(0.0, -0.01) == "w_appr"


def test_aggregate_tmc_means_hourly_across_rows(tmp_path):
    p = tmp_path / "tmc.csv"
    # One location, two 15-min bins in the same (dow, hour): n_appr 100 then 200.
    p.write_text(
        _HEADER
        + "42,2026-06-10,2026-06-10T08:00:00,43.70,-79.40,100,10\n"
        + "42,2026-06-10,2026-06-10T08:15:00,43.70,-79.40,200,30\n"
    )
    agg = aggregate_tmc(str(p))
    vol = agg["vol"][("42", 6, 2, 8)]  # June=6, Wed=2, hour 8
    assert vol["n_appr"] == 600.0  # mean(100,200)=150 ×4 bins/hr
    assert vol["s_appr"] == 80.0  # mean(10,30)=20 ×4
    assert agg["coord"]["42"] == (43.70, -79.40)


def _toy_graph():
    g = nx.MultiDiGraph()
    g.add_node("A", lat=43.70, lon=-79.40)
    g.add_node("B", lat=43.71, lon=-79.40)  # due north of A
    # in-edge to A from its northern neighbour B → carries the n_appr volume
    g.add_edge(
        "B", "A", edge_id="B-A-0", capacity=1000.0, base_time_min=1.0, speed_kmh=50.0, status="open"
    )
    return g


def test_build_model_assigns_approach_volume_to_incident_edge(tmp_path):
    p = tmp_path / "tmc.csv"
    p.write_text(_HEADER + "42,2026-06-10,2026-06-10T08:00:00,43.70,-79.40,150,0\n")
    g = _toy_graph()
    edge_index = {"B-A-0": 0}
    model = build_baseline_model(g, edge_index, tmc_path=str(p))

    assert model.n_matched == 1  # the survey point snapped to node A
    recs = model.records_for_hour(6, 2, 8)  # June, Wed, 08:00
    assert len(recs) == 1
    idx, load, _speed, pressure, closure = recs[0]
    assert idx == 0
    assert load == 600.0  # 150 ×4
    assert abs(pressure - 0.6) < 1e-6  # 600 / 1000
    assert closure == 0

    # An hour/day/month with no survey rows → empty (free-flow).
    assert model.records_for_hour(6, 2, 3) == []  # June Wed 03:00
    assert model.records_for_hour(6, 6, 8) == []  # June Sunday
    assert model.records_for_hour(7, 2, 8) == []  # July (no data that month)
