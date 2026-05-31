"""Per-config train/eval runner for the GNN benchmark (P13 §G).

Two backends, same harness (configs/metrics/compare):

* ``graphsage`` (Spark) — subset the built GNN dataset's columns per config, retrain
  the GraphSAGE baseline, eval val + spatial-holdout. Needs torch/PyG → runs on the
  GB10 via ``scripts/spark/benchmark_gnn.sh``. This is the **real old-vs-new GNN**
  comparison.
* ``ridge`` (local) — a torch-free NumPy ridge regression on a tabular CSV. A fast
  **directional proxy** that exercises the whole harness without the GB10 and probes
  feature effects (esp. the lat/lon memorization claim via spatial-holdout). It is
  NOT GraphSAGE and it runs the *demand* task (predict ``vehicle_count``), where
  ``distance_to_downtown`` is a legitimate feature — so it is **not** the verdict on
  pruning that feature from the *residual* model (see §C). Use it for plumbing +
  the memorization probe; trust the ``graphsage`` backend for the real verdict.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from .compare import compare_configs, render_markdown, write_report
from .metrics import evaluate, spatial_holdout_split

# ── ridge backend (local, NumPy only) ────────────────────────────────────────────
# Feature pool available in data/model/{training,validation}_dataset.csv.
DEMAND_FEATURE_POOL = [
    "lat",
    "lon",
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "weather_code",
    "road_degree",
    "distance_to_downtown",
    "near_highway",
    "road_class_rank",
]
# Demand-task configs (drops applied to the pool above). Honest for this dataset:
# `full` keeps everything; the probes isolate the memorization / demand-prior claims.
DEMAND_CONFIGS = {
    "full": frozenset(),
    "no_latlon": frozenset({"lat", "lon"}),  # memorization probe
    "no_downtown": frozenset({"distance_to_downtown"}),  # demand-prior probe
    "lean": frozenset({"lat", "lon", "distance_to_downtown"}),
}


def _load_tabular(path: Path, features: list[str], target: str, group: str):
    rows = list(csv.DictReader(open(path)))
    X = np.array([[float(r[f] or 0.0) for f in features] for r in rows], dtype=np.float64)
    y = np.array([float(r[target] or 0.0) for r in rows], dtype=np.float64)
    g = np.array([r[group] for r in rows])
    return X, y, g


def _standardize(train: np.ndarray, other: np.ndarray):
    mean = train.mean(axis=0)
    std = train.std(axis=0)
    std[std == 0] = 1.0
    return (train - mean) / std, (other - mean) / std


def _ridge_fit_predict(Xtr, ytr, Xte, lam: float = 1.0) -> np.ndarray:
    """Closed-form ridge: w = (XᵀX + λI)⁻¹ Xᵀy, with a bias column."""
    Xtr_b = np.hstack([Xtr, np.ones((Xtr.shape[0], 1))])
    Xte_b = np.hstack([Xte, np.ones((Xte.shape[0], 1))])
    n_feat = Xtr_b.shape[1]
    reg = lam * np.eye(n_feat)
    reg[-1, -1] = 0.0  # don't regularize bias
    w = np.linalg.solve(Xtr_b.T @ Xtr_b + reg, Xtr_b.T @ ytr)
    return Xte_b @ w


def run_ridge(train_csv: Path, val_csv: Path, *, lam: float = 1.0) -> dict:
    """Train/eval every DEMAND_CONFIG; return {config: {metric: value}}."""
    target, group = "vehicle_count", "location_id"
    Xtr_all, ytr, gtr = _load_tabular(train_csv, DEMAND_FEATURE_POOL, target, group)
    Xva_all, yva, _ = _load_tabular(val_csv, DEMAND_FEATURE_POOL, target, group)
    # spatial-holdout split *within* the training rows (unseen locations)
    ht_train, ht_test = spatial_holdout_split(gtr, test_frac=0.2, seed=42)

    results: dict[str, dict[str, float]] = {}
    for name, drop in DEMAND_CONFIGS.items():
        cols = [i for i, f in enumerate(DEMAND_FEATURE_POOL) if f not in drop]
        Xtr, Xva = Xtr_all[:, cols], Xva_all[:, cols]
        # standard validation (seen locations)
        Xtr_s, Xva_s = _standardize(Xtr, Xva)
        val_pred = _ridge_fit_predict(Xtr_s, ytr, Xva_s, lam)
        m = evaluate(val_pred, yva)
        # spatial holdout (unseen locations) — refit on ht_train, eval ht_test
        Xa, Xb = _standardize(Xtr[ht_train], Xtr[ht_test])
        ho_pred = _ridge_fit_predict(Xa, ytr[ht_train], Xb, lam)
        ho = evaluate(ho_pred, ytr[ht_test])
        m["holdout_mae"] = ho["mae"]
        m["holdout_rmse"] = ho["rmse"]
        results[name] = m
    return results


# ── graphsage backend (Spark / GB10, needs torch+PyG) ────────────────────────────
# The REAL same-task A/B: train main's GraphSAGE on each feature config (same data,
# split, seed; only the columns vary). The dataset's val split is grouped by location
# (ingest_real_data.split_and_write), so val error already measures unseen-location
# generalization — the spatial-holdout probe for the lat/lon prune comes for free.
GRAPHSAGE_CONFIGS = ("baseline", "lean", "pruned", "ablate_downtown", "ablate_redundant")


def _subset_dataset(ds: dict, drop_node, drop_edge, fit_standardizer):
    """Return a copy of the built dataset with node/edge columns dropped by name."""
    nn_, en = ds["node_feature_names"], ds["edge_feature_names"]
    keep_n = [i for i, n in enumerate(nn_) if n not in drop_node]
    keep_e = [i for i, n in enumerate(en) if n not in drop_edge]
    xr, er = ds["x_raw"][:, keep_n], ds["edge_attr_raw"][:, keep_e]
    ns, es = fit_standardizer(xr), fit_standardizer(er)
    new = dict(ds)
    new["x_raw"], new["edge_attr_raw"] = xr, er
    new["x"] = (xr - ns["mean"]) / ns["std"]
    new["edge_attr"] = (er - es["mean"]) / es["std"]
    new["node_standardizer"], new["edge_standardizer"] = ns, es
    new["node_feature_names"] = [nn_[i] for i in keep_n]
    new["edge_feature_names"] = [en[i] for i in keep_e]
    return new


def run_graphsage(
    graph_path: Path, out_dir: Path, *, epochs: int = 30, seeds=(42, 1, 7), configs=None
) -> dict:
    """Train GraphSAGE per feature config across seeds; return mean {config: metrics}.

    Each config trains over ``seeds`` on the SAME column-subset dataset; metrics are
    the mean across seeds (the per-seed spread is printed so noise is visible). Spark-only.
    """
    import torch  # noqa: WPS433 (lazy — torch lives on the GB10)

    from models.gnn.build_gnn_dataset import build_dataset
    from models.gnn.train_gnn import train
    from models.gnn.utils import fit_standardizer

    from .configs import REGISTRY

    configs = configs or {k: REGISTRY[k] for k in GRAPHSAGE_CONFIGS}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    full_path = out_dir / "gnn_dataset_full.pt"
    if not full_path.exists():
        build_dataset(graph_path=Path(graph_path), output=full_path)
    full = torch.load(full_path, map_location="cpu", weights_only=False)

    keys = ("mae", "rmse", "r2", "risk_accuracy")
    results: dict[str, dict[str, float]] = {}
    for name, cfg in configs.items():
        sub = _subset_dataset(full, cfg.drop_node, cfg.drop_edge, fit_standardizer)
        sub_path = out_dir / f"dataset_{name}.pt"
        torch.save(sub, sub_path)
        print(
            f"\n=== config {name}: node_feat={sub['x'].shape[1]} "
            f"edge_feat={sub['edge_attr'].shape[1]} · seeds={list(seeds)} ==="
        )
        per_seed = []
        for seed in seeds:
            m = train(
                dataset_path=sub_path,
                graph_path=Path(graph_path),
                model_path=out_dir / f"model_{name}_s{seed}.pt",
                metrics_path=out_dir / f"metrics_{name}_s{seed}.json",
                epochs=epochs,
                seed=seed,
                backend="graphsage",
            )
            per_seed.append({k: m["val"][k] for k in keys if m["val"].get(k) is not None})
        # aggregate to mean; print spread so the noise is explicit
        agg = {}
        for k in per_seed[0]:
            vals = [sm[k] for sm in per_seed]
            agg[k] = float(np.mean(vals))
            print(
                f"  {name:18s} {k:13s} mean={np.mean(vals):.4f} "
                f"std={np.std(vals):.4f} seeds={[round(x, 4) for x in vals]}"
            )
        results[name] = agg
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="GNN benchmark runner (P13 §G).")
    ap.add_argument("--backend", choices=["ridge", "graphsage"], default="ridge")
    ap.add_argument("--train", type=Path, default=Path("data/model/training_dataset.csv"))
    ap.add_argument("--val", type=Path, default=Path("data/model/validation_dataset.csv"))
    ap.add_argument("--graph", type=Path, default=Path("data/graph/toronto_drive_graph.json"))
    ap.add_argument("--out-dir", type=Path, default=Path("data/gnn"))
    ap.add_argument("--out-json", type=Path, default=Path("data/gnn/benchmark_report.json"))
    ap.add_argument("--out-md", type=Path, default=Path("data/gnn/benchmark_report.md"))
    ap.add_argument("--reference", default=None)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--seeds", default="42,1,7", help="comma-separated seeds (graphsage)")
    ap.add_argument("--lam", type=float, default=1.0)
    args = ap.parse_args(argv)

    if args.backend == "graphsage":
        seeds = tuple(int(s) for s in str(args.seeds).split(",") if s.strip())
        results = run_graphsage(args.graph, args.out_dir, epochs=args.epochs, seeds=seeds)
        reference = args.reference or "baseline"
        tail = "[GraphSAGE — real same-task A/B on the GB10"
    else:
        results = run_ridge(args.train, args.val, lam=args.lam)
        reference = args.reference or "full"
        tail = "[ridge proxy — NOT GraphSAGE; demand task"

    comparison = compare_configs(results, reference=reference)
    write_report(comparison, args.out_json, args.out_md)
    print(render_markdown(comparison))
    print(f"\n{tail}. wrote {args.out_md}]")


if __name__ == "__main__":
    main()
