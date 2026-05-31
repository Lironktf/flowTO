"""P09 — demand_surge op: OD injection, sim integration, and op-splitting."""

from __future__ import annotations

import networkx as nx
import pytest

from torontosim.graph import schema
from torontosim.simulation.demand import apply_demand_surge
from torontosim.simulation.simulate_traffic import apply_scenario, simulate_scenario


def _graph():
    g = nx.MultiDiGraph()
    coords = {0: (-79.41, 43.63), 1: (-79.40, 43.63), 2: (-79.40, 43.64)}
    for n, (x, y) in coords.items():
        g.add_node(n, x=x, y=y)
    edges = [("e01", 0, 1), ("e10", 1, 0), ("e12", 1, 2), ("e21", 2, 1)]
    for eid, u, v in edges:
        g.add_edge(
            u,
            v,
            key=0,
            **schema.make_edge(
                edge_id=eid,
                from_node=u,
                to_node=v,
                road_name=f"Road {eid}",
                road_class="primary",
                length_m=500.0,
                speed_kmh=50.0,
                lanes=2.0,
                capacity=600.0,
                base_time_min=0.6,
                one_way=False,
                geometry=[[0, 0], [0, 0]],
            ),
        )
    return g


def test_apply_demand_surge_adds_trips_at_origin():
    g = _graph()
    od = [{"origin": 1, "destination": 2, "trips": 100.0}]
    out = apply_demand_surge(od, g, node_id=0, amount=500.0, mode="absolute")
    assert sum(e["trips"] for e in out) > sum(e["trips"] for e in od)
    added = [e for e in out if e["origin"] == 0]
    assert added, "surge must inject trips originating at the surge node"
    assert abs(sum(e["trips"] for e in added) - 500.0) < 1e-6  # absolute = total added


def test_apply_demand_surge_resolves_point_to_nearest_node():
    g = _graph()
    od = [{"origin": 1, "destination": 2, "trips": 100.0}]
    # A point right at node 0 → origin resolves to node 0.
    out = apply_demand_surge(od, g, lng=-79.41, lat=43.63, amount=300.0)
    assert any(e["origin"] == 0 for e in out)


def test_apply_demand_surge_degrades_gracefully_when_unresolvable():
    g = _graph()
    od = [{"origin": 1, "destination": 2, "trips": 100.0}]
    out = apply_demand_surge(od, g, node_id=999, amount=500.0)  # node not in graph
    assert out == od


def test_simulate_scenario_accepts_demand_surge_and_grows_demand():
    g = _graph()
    od = [{"origin": 0, "destination": 2, "trips": 100.0}]
    base = simulate_scenario(g, od, [], iterations=2, recompute="full")
    surged = simulate_scenario(
        g,
        od,
        [{"op": "demand_surge", "node_id": 0, "amount": 2000.0}],
        iterations=2,
        recompute="full",
    )
    # The surge OD was injected and actually used by the solver.
    assert len(surged["od_matrix"]) > len(base["od_matrix"])
    assert sum(e["trips"] for e in surged["od_matrix"]) > sum(e["trips"] for e in base["od_matrix"])


def test_demand_surge_must_be_split_before_apply_scenario():
    # apply_scenario is graph-only and rejects demand_surge — proving simulate_scenario
    # must (and does) split it out into the OD transform.
    g = _graph()
    with pytest.raises(ValueError):
        apply_scenario(g, [{"op": "demand_surge", "node_id": 0, "amount": 100.0}])
