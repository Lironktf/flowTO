"""Pure-NumPy benchmark metrics + the spatial-holdout splitter.

Torch-free so the harness runs and unit-tests locally. Mirrors the error metrics
in ``models/gnn/utils.py`` (mae/rmse/r2) plus a risk-bucket accuracy, a top-K
impacted-edge overlap (what the optimizer consumes), and a group-wise
spatial-holdout split that guarantees no ``centreline_id`` leaks across train/test.
"""

from __future__ import annotations

import numpy as np

# Pressure → risk bucket thresholds (match models/gnn/utils.pressure_to_risk:
# low <0.5 · moderate <0.75 · high <1.0 · severe ≥1.0).
RISK_EDGES = (0.5, 0.75, 1.0)


def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=np.float64)


def mae(pred, target) -> float:
    p, t = _arr(pred), _arr(target)
    return float(np.mean(np.abs(p - t)))


def rmse(pred, target) -> float:
    p, t = _arr(pred), _arr(target)
    return float(np.sqrt(np.mean((p - t) ** 2)))


def r2(pred, target) -> float:
    p, t = _arr(pred), _arr(target)
    ss_res = float(np.sum((t - p) ** 2))
    ss_tot = float(np.sum((t - np.mean(t)) ** 2))
    if ss_tot == 0.0:
        # constant target: perfect iff residual is zero, else undefined → 0.0
        return 1.0 if ss_res == 0.0 else 0.0
    return 1.0 - ss_res / ss_tot


def risk_bucket(values, edges: tuple[float, ...] = RISK_EDGES) -> np.ndarray:
    """Bucketize pressures into ordinal risk classes (0=low … 3=severe)."""
    return np.digitize(_arr(values), edges, right=False)


def risk_accuracy(pred, target, edges: tuple[float, ...] = RISK_EDGES) -> float:
    """Fraction of edges whose predicted risk bucket matches the observed bucket."""
    p = risk_bucket(pred, edges)
    t = risk_bucket(target, edges)
    if p.size == 0:
        return 0.0
    return float(np.mean(p == t))


def rank_topk_overlap(pred, target, k: int) -> float:
    """Overlap of the top-k edges by |value| between pred and target (Jaccard-ish).

    Returns |topk(pred) ∩ topk(target)| / k. This is the "did we flag the worst
    edges" metric the optimizer (P10) actually cares about — exact flow matters
    less than ranking.
    """
    p, t = _arr(pred), _arr(target)
    k = int(min(k, p.size))
    if k <= 0:
        return 0.0
    top_p = set(np.argsort(-np.abs(p))[:k].tolist())
    top_t = set(np.argsort(-np.abs(t))[:k].tolist())
    return len(top_p & top_t) / k


def evaluate(pred, target, *, topk: int | None = None) -> dict[str, float]:
    """Bundle the standard error metrics for one config's predictions."""
    out = {
        "mae": mae(pred, target),
        "rmse": rmse(pred, target),
        "r2": r2(pred, target),
        "risk_accuracy": risk_accuracy(pred, target),
    }
    if topk:
        out[f"rank_top{topk}_overlap"] = rank_topk_overlap(pred, target, topk)
    return out


def spatial_holdout_split(
    group_ids, test_frac: float = 0.2, seed: int = 42
) -> tuple[np.ndarray, np.ndarray]:
    """Group-wise split: whole groups go to test, so no group_id leaks.

    ``group_ids`` is a per-sample array (e.g. centreline_id). Returns
    ``(train_mask, test_mask)`` boolean arrays. Deterministic for a fixed seed.
    This is the unseen-location generalization probe for the lat/lon prune.
    """
    ids = np.asarray(group_ids)
    uniq = np.unique(ids)
    rng = np.random.default_rng(seed)
    order = rng.permutation(uniq.shape[0])
    n_test_groups = max(1, int(round(test_frac * uniq.shape[0]))) if uniq.shape[0] else 0
    test_groups = set(uniq[order[:n_test_groups]].tolist())
    test_mask = np.array([gid in test_groups for gid in ids], dtype=bool)
    return ~test_mask, test_mask
