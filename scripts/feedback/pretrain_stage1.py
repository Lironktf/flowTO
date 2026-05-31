"""Stage-1 residual pre-train on the full Centreline graph, saving a checkpoint (GB10).

Stage-2's warm-start needs a saved Stage-1 *residual* model — and it must be trained on
the **same** graph + grounded OD Stage-2 uses. This builds the Centreline graph, grounds
an OD on real TMC counts, generates sim scenario pairs (capped equilibrium for speed),
trains the residual GNN, and writes ``models/gnn/stage1_residual.pt``.

Run on the box:
  timeout 590 bash scripts/spark/run.sh \
    "PYTHONPATH=.:src python scripts/feedback/pretrain_stage1.py"
"""

from __future__ import annotations

import argparse
import time

from torontosim.feedback.scenario_gen import generate_from_sim
from torontosim.feedback.stage2_inputs import DEFAULT_GRAPH, grounded_od, load_graph
from torontosim.feedback.train_residual import train_stage1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pretrain_stage1")
    p.add_argument("--graph", default=DEFAULT_GRAPH)
    p.add_argument("--ckpt", default="models/gnn/stage1_residual.pt")
    p.add_argument("--scenarios", type=int, default=200)
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--hidden-dim", type=int, default=64)
    p.add_argument("--max-pairs", type=int, default=2000)
    p.add_argument("--sim-backend", default="gpu",
                   help="equilibrium solver backend: gpu (cuGraph) | scipy | cpu")
    p.add_argument("--solver", default="full", choices=["full", "blast"],
                   help="full = whole-equilibrium per scenario (closures+openings); "
                        "blast = re-route affected bundles only (fast, closures only)")
    p.add_argument("--max-iter", type=int, default=25)
    p.add_argument("--rgap", type=float, default=1e-3)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    graph = load_graph(args.graph)
    print(f"graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

    t0 = time.time()
    od = grounded_od(graph, max_pairs=args.max_pairs)
    print(f"grounded OD: {len(od):,} trips in {time.time() - t0:.0f}s")

    t1 = time.time()
    pairs = generate_from_sim(
        graph, od, n=args.scenarios, seed=0, solver=args.solver,
        backend=args.sim_backend, max_iter=args.max_iter, rgap=args.rgap,
    )
    print(
        f"scenario gen: {pairs['scenario_id'].nunique()} scenarios, {len(pairs):,} rows "
        f"in {time.time() - t1:.0f}s · "
        f"signs={pairs.groupby('scenario_id')['sign'].first().value_counts().to_dict()}"
    )

    t2 = time.time()
    m = train_stage1(
        graph, pairs, epochs=args.epochs, hidden_dim=args.hidden_dim, seed=args.seed,
        ckpt_path=args.ckpt,
    )
    print(f"train: {time.time() - t2:.0f}s · saved {args.ckpt}")
    for k, v in m.items():
        print(f"  {k}: {v}")
    print(
        "\nbeats zero-predictor on AFFECTED edges: "
        f"{m['val_mae_affected'] < m['zero_val_mae_affected']}  "
        f"({m['val_mae_affected']:.4f} vs {m['zero_val_mae_affected']:.4f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
