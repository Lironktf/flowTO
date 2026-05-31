"""Stage-1 end-to-end smoke on the REAL sim (GB10 only).

Grid network → scenario-generator pairs (real Frank-Wolfe sim) → train the residual
GNN → confirm it learns the sim's reroute residual (beats the zero-predictor).
"""

from __future__ import annotations

import networkx as nx

from torontosim.feedback.scenario_gen import generate_from_sim
from torontosim.feedback.train_residual import train_stage1
from torontosim.graph import schema


def grid(n: int = 3) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    coord = {}
    for r in range(n):
        for c in range(n):
            nid = r * n + c
            coord[nid] = (-79.40 + 0.01 * c, 43.64 + 0.01 * r)
            g.add_node(nid, x=coord[nid][0], y=coord[nid][1])
    eid = 0

    def add(u, v):
        nonlocal eid
        g.add_edge(u, v, key=0, **schema.make_edge(
            edge_id=f"e{eid}", from_node=u, to_node=v, road_class="primary",
            length_m=1000.0, speed_kmh=50.0, lanes=2.0, capacity=1200.0,
            base_time_min=1.2, one_way=True,
            geometry=[[coord[u][1], coord[u][0]], [coord[v][1], coord[v][0]]],
        ))
        eid += 1

    for r in range(n):
        for c in range(n):
            nid = r * n + c
            if c + 1 < n:
                add(nid, nid + 1); add(nid + 1, nid)
            if r + 1 < n:
                add(nid, nid + n); add(nid + n, nid)
    return g


def main() -> None:
    g = grid(5)  # 25 nodes, ~80 directed edges → up to 80 scenarios
    od = [
        {"origin": 0, "destination": 24, "trips": 3000.0},
        {"origin": 4, "destination": 20, "trips": 2000.0},
        {"origin": 12, "destination": 0, "trips": 1500.0},
    ]
    pairs = generate_from_sim(g, od, n=80, seed=0)
    print(f"scenarios: {pairs['scenario_id'].nunique()} · pair rows: {len(pairs)} · "
          f"signs: {pairs.groupby('scenario_id')['sign'].first().value_counts().to_dict()}")

    m = train_stage1(g, pairs, epochs=200, hidden_dim=64, seed=42)
    for k, v in m.items():
        print(f"  {k}: {v}")
    print(f"\nSTAGE-1 beats the zero-predictor on AFFECTED edges: "
          f"{m['val_mae_affected'] < m['zero_val_mae_affected']}  "
          f"({m['val_mae_affected']:.4f} vs {m['zero_val_mae_affected']:.4f})")


if __name__ == "__main__":
    main()
