"""P10 — heuristic optimizer: sim-verified, improving-or-neutral, deterministic."""

from __future__ import annotations

import networkx as nx

from torontosim.api.store import AppState
from torontosim.graph import schema
from torontosim.optimizer import propose


def _bottleneck_state():
    """A diamond where one branch is a tight arterial bottleneck."""
    g = nx.MultiDiGraph()
    coords = {0: (-79.40, 43.64), 1: (-79.39, 43.65), 2: (-79.39, 43.63), 3: (-79.38, 43.64)}
    for n, (x, y) in coords.items():
        g.add_node(n, x=x, y=y)
    # Two parallel routes 0->3; the "1" branch is low-capacity (bottleneck).
    specs = [
        ("e_in_top", 0, 1, 600.0),
        ("e_in_bot", 0, 2, 2400.0),
        ("e_out_top", 1, 3, 600.0),
        ("e_out_bot", 2, 3, 2400.0),
    ]
    for eid, u, v, cap in specs:
        g.add_edge(
            u,
            v,
            key=0,
            **schema.make_edge(
                edge_id=eid,
                from_node=u,
                to_node=v,
                road_class="primary",
                length_m=1000.0,
                speed_kmh=50.0,
                lanes=2.0,
                capacity=cap,
                base_time_min=1.2,
            ),
        )
    od = [{"origin": 0, "destination": 3, "trips": 3000.0}]
    return AppState.from_graph(g, od, weather="clear", time_context={"hour": 17})


def test_propose_returns_improving_or_neutral_plan():
    state = _bottleneck_state()
    out = propose(state, {"objective": "average_pressure", "max_actions": 2})
    assert out["solver"] == "heuristic"
    # The simulated best metric is no worse than do-nothing.
    assert out["best_metric"] <= out["baseline_metric"] + 1e-9
    assert out["improvement"] >= 0.0
    # Plan is budget-valid.
    assert out["plan_cost"] <= 100.0


def test_propose_is_deterministic():
    a = propose(_bottleneck_state(), {})
    b = propose(_bottleneck_state(), {})
    assert a["best_metric"] == b["best_metric"]
    assert [iv["edge_id"] for iv in a["plan"]] == [iv["edge_id"] for iv in b["plan"]]


def test_propose_candidates_scored_by_sim():
    out = propose(_bottleneck_state(), {"candidate_k": 4})
    # Each candidate carries a simulated metric + improvement.
    for c in out["candidates"]:
        assert "metric" in c and "improvement" in c
