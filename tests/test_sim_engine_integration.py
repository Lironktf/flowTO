"""P04 T04.8 — equilibrium engine wired into simulate_traffic (small graph).

Validates the engine/congestion_model/backend flags on a tiny canonical-schema
graph: equilibrium produces the stable frame schema, loads the network, is
deterministic, and the kpath default path is untouched.
"""

from __future__ import annotations

import networkx as nx

from torontosim.graph import schema
from torontosim.simulation.simulate_traffic import simulate_traffic


def _small_graph():
    """A 4-node diamond with two parallel routes, canonical edge schema."""
    g = nx.MultiDiGraph()
    coords = {0: (-79.40, 43.64), 1: (-79.39, 43.65), 2: (-79.39, 43.63), 3: (-79.38, 43.64)}
    for n, (x, y) in coords.items():
        g.add_node(n, x=x, y=y)
    edges = [(0, 1), (0, 2), (1, 3), (2, 3)]
    for i, (u, v) in enumerate(edges):
        g.add_edge(
            u,
            v,
            key=0,
            **schema.make_edge(
                edge_id=f"e{i}",
                from_node=u,
                to_node=v,
                road_class="primary",
                length_m=1000.0,
                speed_kmh=50.0,
                lanes=2.0,
                capacity=1200.0,
                base_time_min=1.2,
                one_way=True,
                geometry=[[coords[u][1], coords[u][0]], [coords[v][1], coords[v][0]]],
            ),
        )
    return g


OD = [{"origin": 0, "destination": 3, "trips": 2000.0}]


def test_equilibrium_engine_loads_and_frames():
    g = _small_graph()
    res = simulate_traffic(
        g,
        OD,
        iterations=4,
        engine="equilibrium",
        congestion_model="bpr",
        auto_calibrate=False,
    )
    assert res["engine"] == "equilibrium"
    assert res["congestion_model"] == "bpr"
    assert len(res["frames"]) == 4  # stable frame schema preserved
    assert res["summary"]["total_assigned_trips"] >= 0
    # Demand of 2000 split across the two parallel routes -> both branches load.
    loads = {d["edge_id"]: d.get("load", 0.0) for _u, _v, d in res["graph"].edges(data=True)}
    assert sum(loads.values()) > 0
    assert res["converged"] is True
    assert "rgap" in res


def test_equilibrium_engine_deterministic():
    a = simulate_traffic(
        _small_graph(),
        OD,
        iterations=4,
        engine="equilibrium",
        congestion_model="bpr",
        auto_calibrate=False,
    )
    b = simulate_traffic(
        _small_graph(),
        OD,
        iterations=4,
        engine="equilibrium",
        congestion_model="bpr",
        auto_calibrate=False,
    )
    la = sorted((d["edge_id"], d["load"]) for _u, _v, d in a["graph"].edges(data=True))
    lb = sorted((d["edge_id"], d["load"]) for _u, _v, d in b["graph"].edges(data=True))
    assert la == lb


def test_kpath_default_still_runs():
    g = _small_graph()
    res = simulate_traffic(g, OD, iterations=4, auto_calibrate=False)
    assert res["engine"] == "kpath"
    assert res["congestion_model"] == "legacy"
    assert len(res["frames"]) == 4
