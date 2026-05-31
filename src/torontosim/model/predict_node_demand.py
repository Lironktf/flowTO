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
)
from .train_demand_model import MODEL_PATH


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
        X = np.asarray(X, dtype=float)
        out = np.empty(len(X))
        for i, row in enumerate(X):
            out[i] = self._one(row)
        return out

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

        try:
            return joblib.load(model_path)
        except Exception as exc:
            # The committed model may use an optional backend such as XGBoost.
            # Keep the CPU demo runnable when that backend or its native runtime
            # is unavailable.
            print(
                f"[predict] trained model at {model_path} could not be loaded "
                f"({type(exc).__name__}); using HeuristicDemandModel"
            )
    else:
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
    static = compute_static_node_features(graph)

    node_ids = list(static.keys())
    X = np.array([build_feature_row(static[n], tc) for n in node_ids], dtype=float)
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
