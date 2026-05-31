"""Stage-1 at real scale on the 18k-edge Toronto graph (GB10 only).

Loads the real OSMnx downtown graph, builds a high-demand OD over its busiest nodes,
generates scenario pairs via the real Frank-Wolfe sim, and trains the residual GNN.
"""

from __future__ import annotations

import time

from torontosim.feedback.scenario_gen import generate_from_sim
from torontosim.feedback.train_residual import train_stage1
from torontosim.graph.routing import import_graph_json

N_SCENARIOS = 12


def main() -> None:
    g = import_graph_json("data/graph/toronto_drive_graph.json")
    print(f"graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")

    # denser OD over the busiest 60 nodes → more of the 18k edges carry flow
    hubs = sorted(g.nodes, key=lambda n: g.degree(n), reverse=True)[:60]
    od = [
        {"origin": hubs[i], "destination": hubs[(i * 7 + 13) % 60], "trips": 1200.0}
        for i in range(60)
        if hubs[i] != hubs[(i * 7 + 13) % 60]
    ]

    t0 = time.time()
    # capped equilibrium (max_iter/rgap) keeps each solve fast — approximate
    # equilibrium is fine for Stage-1 training pairs.
    pairs = generate_from_sim(g, od, n=N_SCENARIOS, seed=0, max_iter=25, rgap=1e-3)
    print(f"scenario gen: {pairs['scenario_id'].nunique()} scenarios, "
          f"{len(pairs):,} rows, {time.time() - t0:.0f}s · "
          f"signs={pairs.groupby('scenario_id')['sign'].first().value_counts().to_dict()}")

    t1 = time.time()
    m = train_stage1(g, pairs, epochs=100, hidden_dim=64, seed=42)
    print(f"train: {time.time() - t1:.0f}s")
    for k, v in m.items():
        print(f"  {k}: {v}")
    print(f"\nbeats zero-predictor on AFFECTED edges: "
          f"{m['val_mae_affected'] < m['zero_val_mae_affected']}  "
          f"({m['val_mae_affected']:.4f} vs {m['zero_val_mae_affected']:.4f})")


if __name__ == "__main__":
    main()
