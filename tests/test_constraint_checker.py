"""P10 — optimizer action masks + budget."""

from __future__ import annotations

import networkx as nx

from torontosim.graph import schema
from torontosim.optimizer.constraints import mask_action, plan_cost, within_budget


def _graph():
    g = nx.MultiDiGraph()
    g.add_node(0, x=-79.4, y=43.64)
    g.add_node(1, x=-79.39, y=43.64)
    g.add_node(2, x=-79.38, y=43.64)
    g.add_edge(
        0,
        1,
        key=0,
        **schema.make_edge(
            edge_id="art",
            from_node=0,
            to_node=1,
            road_class="primary",
            length_m=500.0,
            speed_kmh=50.0,
            lanes=2.0,
            capacity=1200.0,
            base_time_min=0.6,
        ),
    )
    g.add_edge(
        1,
        2,
        key=0,
        **schema.make_edge(
            edge_id="res",
            from_node=1,
            to_node=2,
            road_class="residential",
            length_m=300.0,
            speed_kmh=30.0,
            lanes=1.0,
            capacity=400.0,
            base_time_min=0.6,
        ),
    )
    return g


def test_residential_capacity_boost_is_masked():
    g = _graph()
    ok, reason = mask_action({"op": "change_capacity", "edge_id": "res", "multiplier": 1.5}, g)
    assert ok is False
    assert "residential" in reason


def test_arterial_capacity_boost_allowed():
    g = _graph()
    ok, _ = mask_action({"op": "change_capacity", "edge_id": "art", "multiplier": 1.5}, g)
    assert ok is True


def test_budget_bounding():
    plan = [
        {"op": "change_capacity", "edge_id": "art", "multiplier": 1.5},
        {"op": "close_edge", "edge_id": "art"},
    ]
    assert plan_cost(plan) == 30.0
    assert within_budget(plan, 100.0) is True
    assert within_budget(plan, 25.0) is False
