"""
Predict baseline car demand per node for a given time context.

    predict_node_demand(graph, model, time_context) -> {node_id: vehicle_demand}

`model` is whatever `load_demand_model()` returns:
  * the trained estimator payload from `train_demand_model` (preferred), or
  * a `HeuristicDemandModel` fallback that needs no training and obeys the same
    `.predict(X)` interface, so the rest of the pipeline never has to care which
    one it got.
"""

from __future__ import annotations

import math
import os
from typing import Dict

import numpy as np

from .features import (
    FEATURE_ORDER,
    build_feature_row,
    compute_static_node_features,
    normalize_time_context,
    rush_factor,
    weather_code,
)
from .train_demand_model import MODEL_PATH

# rush_factor depends only on (hour, is_weekend); precompute the 2x24 table once
# so the vectorized heuristic indexes it instead of calling a Python fn per row.
_RUSH_TABLE = np.array([[rush_factor(h, w) for h in range(24)] for w in (0, 1)], dtype=float)


class HeuristicDemandModel:
    """Trained-model stand-in: predicts demand from features with hand rules.

    Mirrors the relationships baked into the synthetic training data, so the
    pipeline produces sensible output even with no .pkl present. Implements
    `.predict(X)` where X is an array of rows in FEATURE_ORDER.
    """

    kind = "HeuristicDemandModel"
    feature_order = FEATURE_ORDER

    # Column indices into a FEATURE_ORDER row.
    _IDX = {name: i for i, name in enumerate(FEATURE_ORDER)}

    def predict(self, X) -> np.ndarray:
        # Vectorized equivalent of ``_one`` (kept below as the readable spec):
        # same float ops in the same order, so results are identical, but ~30x
        # faster than the per-row Python loop on the full Toronto graph.
        X = np.asarray(X, dtype=float)
        g = self._IDX
        hour = X[:, g["hour"]].astype(np.int64) % 24
        is_weekend = X[:, g["is_weekend"]].astype(np.int64)
        rank = X[:, g["road_class_rank"]].astype(np.int64)
        dist = X[:, g["distance_to_downtown"]]
        near_hw = X[:, g["near_highway"]].astype(np.int64)
        degree = X[:, g["road_degree"]].astype(np.int64)
        wcode = X[:, g["weather_code"]].astype(np.int64)

        base = 300.0
        class_factor = np.full(len(X), 0.5)
        for r, f in {6: 3.2, 5: 2.6, 4: 1.9, 3: 1.35, 2: 0.9, 1: 0.5}.items():
            class_factor[rank == r] = f
        downtown_factor = 1.0 + 2.0 * np.exp(-dist / 4.0)
        highway_factor = np.where(near_hw != 0, 1.3, 1.0)
        degree_factor = 1.0 + 0.05 * np.maximum(0, degree - 2)
        rush = _RUSH_TABLE[(is_weekend != 0).astype(np.int64), hour]
        weather_factor = np.ones(len(X))
        weather_factor[wcode == 2] = 0.92
        weather_factor[wcode == 3] = 0.8
        out = (
            base
            * class_factor
            * downtown_factor
            * highway_factor
            * degree_factor
            * rush
            * weather_factor
        )
        return np.maximum(0.0, out)

    def _one(self, row) -> float:
        g = self._IDX
        hour = int(row[g["hour"]])
        is_weekend = int(row[g["is_weekend"]])
        rank = int(row[g["road_class_rank"]])
        dist = float(row[g["distance_to_downtown"]])
        near_hw = int(row[g["near_highway"]])
        degree = int(row[g["road_degree"]])
        wcode = int(row[g["weather_code"]])

        base = 300.0
        class_factor = {6: 3.2, 5: 2.6, 4: 1.9, 3: 1.35, 2: 0.9, 1: 0.5}.get(rank, 0.5)
        downtown_factor = 1.0 + 2.0 * math.exp(-dist / 4.0)
        highway_factor = 1.3 if near_hw else 1.0
        degree_factor = 1.0 + 0.05 * max(0, degree - 2)
        rush = rush_factor(hour, is_weekend)
        weather_factor = {0: 1.0, 1: 1.0, 2: 0.92, 3: 0.8}.get(wcode, 1.0)
        return max(
            0.0,
            base
            * class_factor
            * downtown_factor
            * highway_factor
            * degree_factor
            * rush
            * weather_factor,
        )


def load_demand_model(model_path: str = MODEL_PATH):
    """Load the trained model payload, or fall back to the heuristic model."""
    if os.path.exists(model_path):
        import joblib

        payload = joblib.load(model_path)
        return payload
    print(f"[predict] no trained model at {model_path}; using HeuristicDemandModel")
    return {
        "model": HeuristicDemandModel(),
        "feature_order": FEATURE_ORDER,
        "kind": "HeuristicDemandModel",
    }


def _estimator_and_order(model):
    """Accept either a payload dict, a bare estimator, or the heuristic model."""
    if isinstance(model, dict):
        return model["model"], model.get("feature_order", FEATURE_ORDER)
    if hasattr(model, "predict"):
        return model, getattr(model, "feature_order", FEATURE_ORDER)
    raise TypeError(f"unsupported model object: {type(model)!r}")


# Column indices of the time-dependent features (the only ones that change
# between predict calls); everything else is static node geometry/topology.
_TIME_COLS = ("hour", "day_of_week", "month", "is_weekend", "weather_code")
_TIME_COL_IDX = {name: FEATURE_ORDER.index(name) for name in _TIME_COLS}

# id(graph) -> ((n_nodes, n_edges), node_ids, base_matrix). Cached so the costly
# static-feature sweep + matrix build runs once per graph instead of per call.
_STATIC_MATRIX_CACHE: dict = {}


def _static_feature_matrix(graph):
    """Return ``(node_ids, base_X)`` with static columns filled, time cols zeroed.

    The static node features depend only on the graph, so we compute them and
    assemble the feature matrix once and cache it; per-call prediction just
    overwrites the five time columns. Keyed on graph identity + (n_nodes,
    n_edges) so add/remove mutations invalidate the cache.
    """
    key = id(graph)
    sig = (graph.number_of_nodes(), graph.number_of_edges())
    cached = _STATIC_MATRIX_CACHE.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1], cached[2]
    static = compute_static_node_features(graph)
    node_ids = list(static.keys())
    zero_tc = {"hour": 0, "day_of_week": 0, "month": 0, "is_weekend": 0, "weather": "clear"}
    base = np.array([build_feature_row(static[n], zero_tc) for n in node_ids], dtype=float)
    _STATIC_MATRIX_CACHE[key] = (sig, node_ids, base)
    return node_ids, base


def predict_node_demand(graph, model, time_context: dict) -> Dict[object, float]:
    """Return {node_id: predicted vehicle demand} for every featurisable node.

    `model` may be the payload from `load_demand_model`/`train_demand_model`, a
    bare sklearn estimator, or a `HeuristicDemandModel`.
    """
    estimator, order = _estimator_and_order(model)
    if order != FEATURE_ORDER:
        # Defensive: we only know how to build FEATURE_ORDER rows here.
        raise ValueError(
            "model was trained on a different feature order than the current "
            f"code:\n  model: {order}\n  code:  {FEATURE_ORDER}"
        )

    tc = normalize_time_context(time_context)
    node_ids, base = _static_feature_matrix(graph)

    # Only the time columns change between calls; copy the cached static matrix
    # and overwrite them (identical to rebuilding every row via build_feature_row).
    X = base.copy()
    X[:, _TIME_COL_IDX["hour"]] = tc["hour"]
    X[:, _TIME_COL_IDX["day_of_week"]] = tc["day_of_week"]
    X[:, _TIME_COL_IDX["month"]] = tc["month"]
    X[:, _TIME_COL_IDX["is_weekend"]] = tc["is_weekend"]
    X[:, _TIME_COL_IDX["weather_code"]] = weather_code(tc["weather"])
    preds = np.asarray(estimator.predict(X), dtype=float)
    preds = np.clip(preds, 0.0, None)  # demand can't be negative

    return {node: float(p) for node, p in zip(node_ids, preds)}


if __name__ == "__main__":
    # Quick smoke run.
    from ..graph.routing import import_graph_json
    from .train_demand_model import GRAPH_JSON

    g = import_graph_json(GRAPH_JSON)
    m = load_demand_model()
    demand = predict_node_demand(
        g, m, {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}
    )
    top = sorted(demand.items(), key=lambda kv: -kv[1])[:10]
    print(f"model: {m.get('kind')}  nodes: {len(demand):,}")
    print("top demand nodes:")
    for node, d in top:
        print(f"  {g.nodes[node].get('name')!s:50} {d:8.0f}")
