"""Validate the scenario generator against the REAL Frank-Wolfe sim (GB10 only).

A 4-node diamond with two parallel routes (A: 0->1->3 via e0,e2 · B: 0->2->3 via
e1,e3). Closing e0 must reroute flow onto route B — proving generate_pairs emits real
physics residuals, not stub numbers.
"""

from __future__ import annotations

import networkx as nx

from torontosim.feedback.groundtruth.counterfactual import simulate_open_intervened
from torontosim.feedback.scenario_gen import generate_pairs
from torontosim.graph import schema

COORDS = {0: (-79.40, 43.64), 1: (-79.39, 43.65), 2: (-79.39, 43.63), 3: (-79.38, 43.64)}
EDGES = [(0, 1), (0, 2), (1, 3), (2, 3)]


def diamond():
    g = nx.MultiDiGraph()
    for n, (x, y) in COORDS.items():
        g.add_node(n, x=x, y=y)
    for i, (u, v) in enumerate(EDGES):
        g.add_edge(u, v, key=0, **schema.make_edge(
            edge_id=f"e{i}", from_node=u, to_node=v, road_class="primary",
            length_m=1000.0, speed_kmh=50.0, lanes=2.0, capacity=1200.0,
            base_time_min=1.2, one_way=True,
            geometry=[[COORDS[u][1], COORDS[u][0]], [COORDS[v][1], COORDS[v][0]]],
        ))
    return g


def main() -> None:
    g = diamond()
    od = [{"origin": 0, "destination": 3, "trips": 2000.0}]
    sim_open, sim_int = simulate_open_intervened(g, od)
    ivs = [{"id": "s0", "edge_id": "e0", "sign": "closure",
            "ops": [{"op": "close_edge", "edge_id": "e0"}]}]
    pairs = generate_pairs(ivs, sim_open, sim_int)
    print(pairs.to_string(index=False))

    d = pairs.set_index("edge_id")["delta_flow"]
    print("\nchecks:")
    print(f"  e0 (closed) delta < 0 : {d['e0'] < 0}  ({d['e0']:.1f})")
    print(f"  e3 (route B) delta > 0: {d['e3'] > 0}  ({d['e3']:.1f})")
    print(f"  flow conserved-ish (|sum delta| small): {abs(d.sum()):.1f}")


if __name__ == "__main__":
    main()
