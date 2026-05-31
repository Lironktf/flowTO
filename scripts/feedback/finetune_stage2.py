"""Stage-2 — real-closure fine-tune + activation gate on the full Centreline graph (GB10).

The feedback step. Pipeline:

  Centreline graph → P14 factory rows (real closures) → counts-grounded OD →
  real residuals (sim OPEN vs CLOSED, r_obs = observed − sim_open) → warm-start the
  Stage-1 residual model → fine-tune on r_obs → ACTIVATION GATE.

Ships the GNN **iff** it beats the sim's own residual on held-out real closures; else
keeps the sim — reported honestly. Writes ``data/gnn/stage2_metrics.json``.

Run on the box (Stage-1 ckpt auto-pretrained if missing):
  timeout 590 bash scripts/spark/run.sh \
    "PYTHONPATH=.:src python scripts/feedback/finetune_stage2.py --v3 data/dataset/v3.csv"
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time

import pandas as pd

from torontosim.feedback.gate import activation_gate
from torontosim.feedback.groundtruth.clean import clean_restrictions
from torontosim.feedback.groundtruth.labels import build_labels
from torontosim.feedback.groundtruth.spatial import spatial_join, tmc_sites
from torontosim.feedback.groundtruth.temporal import (
    during_aggregate,
    split_during_pre,
    tmc_observations,
)
from torontosim.feedback.real_residuals import (
    assemble_factory_rows,
    build_real_residuals,
)
from torontosim.feedback.scenario_gen import generate_from_sim
from torontosim.feedback.stage2_inputs import (
    DEFAULT_GRAPH,
    TMC_PARQUET,
    TMC_RAW,
    grounded_od,
    load_graph,
)
from torontosim.feedback.train_residual import train_stage1, train_stage2


def _load_tmc_df(csv_path):
    """Real TMC as a DataFrame — the raw CSV if given/present, else the parquet store."""
    if os.path.exists(csv_path):
        return pd.read_csv(csv_path, low_memory=False)
    if os.path.exists(TMC_PARQUET):
        return pd.read_parquet(TMC_PARQUET)
    raise FileNotFoundError(f"no TMC at {csv_path} or {TMC_PARQUET}")


def _finite_triples(held):
    """Drop any held-out edge with a non-finite residual before the gate."""
    keep = [
        i
        for i in range(len(held["r_obs"]))
        if all(math.isfinite(held[k][i]) for k in ("r_obs", "r_gnn", "r_sim"))
    ]
    return (
        [held["r_obs"][i] for i in keep],
        [held["r_gnn"][i] for i in keep],
        [held["r_sim"][i] for i in keep],
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="finetune_stage2")
    p.add_argument("--v3", default="data/dataset/v3.csv", help="CART restrictions snapshot")
    p.add_argument("--tmc", default=TMC_RAW, help="raw TMC CSV")
    p.add_argument("--graph", default=DEFAULT_GRAPH)
    p.add_argument("--stage1-ckpt", default="models/gnn/stage1_residual.pt")
    p.add_argument("--stage2-ckpt", default="models/gnn/stage2_residual.pt")
    p.add_argument("--out", default="data/gnn/stage2_metrics.json")
    p.add_argument("--radius-m", type=float, default=500.0)
    p.add_argument("--max-pairs", type=int, default=2000)
    p.add_argument(
        "--sim-backend",
        default="gpu",
        help="equilibrium solver backend: gpu (cuGraph, GB10) | scipy | cpu; "
        "gpu auto-falls back to cpu if cuGraph errors",
    )
    p.add_argument(
        "--residual-solver",
        default="blast",
        choices=["blast", "full"],
        help="sim solver for BOTH the real residuals and the Stage-1 pretrain "
        "scenario-gen (kept matched so warm-start is method-consistent): "
        "blast = re-route only affected bundles (fast, AON, closures only); "
        "full = re-solve the whole equilibrium (verified, slow, closures+openings)",
    )
    p.add_argument("--max-iter", type=int, default=50)
    p.add_argument("--rgap", type=float, default=1e-3)
    p.add_argument("--epochs", type=int, default=300)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--patience", type=int, default=30)
    p.add_argument("--gate-eps", type=float, default=0.0)
    p.add_argument("--gate-min-n", type=int, default=10)
    p.add_argument("--pretrain-scenarios", type=int, default=200)
    p.add_argument("--pretrain-epochs", type=int, default=100)
    p.add_argument(
        "--limit-closures",
        type=int,
        default=0,
        help="cap #restrictions (0 = all) to bound the CLOSED-solve count",
    )
    args = p.parse_args(argv)

    t_all = time.time()
    graph = load_graph(args.graph)
    print(f"[graph] {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

    # --- P14 factory rows (real closures) -----------------------------------
    tmc = _load_tmc_df(args.tmc)
    restrictions = clean_restrictions(args.v3)
    obs = tmc_observations(tmc)
    sites = tmc_sites(tmc)
    pairs = spatial_join(sites, restrictions, radius_m=args.radius_m)
    during, pre = split_during_pre(pairs, obs)
    dagg = during_aggregate(pairs, obs)
    closures = build_labels(dagg, during, pre)
    factory_rows = assemble_factory_rows(closures, pairs)
    if args.limit_closures and len(factory_rows):
        keep_ids = sorted(factory_rows["ID"].unique())[: args.limit_closures]
        factory_rows = factory_rows[factory_rows["ID"].isin(keep_ids)].reset_index(drop=True)
        print(f"[factory] capped to {len(keep_ids)} restrictions (--limit-closures)")
    print(
        f"[factory] restrictions={restrictions['ID'].nunique()} "
        f"closure-rows={len(closures)} with_count={int(closures['during_vol_mean'].notna().sum())} "
        f"factory_rows={len(factory_rows)} "
        f"split={factory_rows['split'].value_counts().to_dict() if len(factory_rows) else {}}"
    )

    # --- grounded OD (counts-reconciled so r_obs isn't sim error) ------------
    t0 = time.time()
    od = grounded_od(graph, max_pairs=args.max_pairs, tmc_records=tmc.to_dict("records"))
    print(f"[od] grounded {len(od):,} trips in {time.time() - t0:.0f}s")

    # --- real residuals (sim OPEN vs CLOSED) --------------------------------
    t1 = time.time()
    residuals, coverage, sim_open_full = build_real_residuals(
        graph,
        factory_rows,
        od,
        solver=args.residual_solver,
        backend=args.sim_backend,
        max_iter=args.max_iter,
        rgap=args.rgap,
    )
    print(f"[residuals] {coverage} in {time.time() - t1:.0f}s")
    if residuals.empty:
        print("[abort] no real residual rows — nothing to fine-tune. Keeping the sim.")
        _write(args.out, {"coverage": coverage, "verdict": "keep sim (no real residuals)"})
        return 0

    # --- Stage-1 checkpoint (check the box first; pretrain only if missing) --
    if not os.path.exists(args.stage1_ckpt):
        print(f"[stage1] no checkpoint at {args.stage1_ckpt} — pretraining on Centreline")
        t2 = time.time()
        sim_pairs = generate_from_sim(
            graph,
            od,
            n=args.pretrain_scenarios,
            seed=0,
            solver=args.residual_solver,
            backend=args.sim_backend,
            max_iter=args.max_iter,
            rgap=args.rgap,
        )
        train_stage1(
            graph,
            sim_pairs,
            epochs=args.pretrain_epochs,
            hidden_dim=64,
            seed=42,
            ckpt_path=args.stage1_ckpt,
        )
        print(f"[stage1] pretrained + saved in {time.time() - t2:.0f}s")
    else:
        print(f"[stage1] warm-starting from existing {args.stage1_ckpt}")

    # --- Stage-2 fine-tune ---------------------------------------------------
    t3 = time.time()
    s2 = train_stage2(
        graph,
        residuals,
        sim_open_full,
        stage1_ckpt=args.stage1_ckpt,
        epochs=args.epochs,
        lr=args.lr,
        patience=args.patience,
        ckpt_path=args.stage2_ckpt,
    )
    held = s2.pop("held_out")
    print(f"[stage2] {s2} in {time.time() - t3:.0f}s")

    # --- activation gate -----------------------------------------------------
    r_obs, r_gnn, r_sim = _finite_triples(held)
    gate = activation_gate(r_obs, r_gnn, r_sim, eps=args.gate_eps, min_n=args.gate_min_n)
    print(f"\n=== ACTIVATION GATE ===\n{json.dumps(gate, indent=2)}")
    print(
        f"\nVERDICT: {gate['verdict'].upper()}  "
        f"(err_gnn={gate['err_gnn_rmse']:.3f} vs err_sim={gate['err_sim_rmse']:.3f}, n={gate['n']})"
    )

    report = {
        "coverage": coverage,
        "stage2": s2,
        "gate": gate,
        "n_held_out_finite": len(r_obs),
        "openings": "not modeled (real opening yield ~0; Stage-1 sim-pretrain carries opening physics)",
        "params": vars(args),
        "elapsed_s": round(time.time() - t_all, 1),
    }
    _write(args.out, report)
    print(f"\n[done] wrote {args.out} in {report['elapsed_s']:.0f}s")
    return 0


def _write(path, obj) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
