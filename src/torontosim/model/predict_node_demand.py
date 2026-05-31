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

import functools
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


# GNN artifacts (repo-root-relative). The GNN is an interchangeable demand
# source: like xgboost it answers ``predict_node_demand`` — it predicts per-edge
# congestion, which we aggregate into per-node demand below.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GNN_MODEL_PATH = os.path.join(_REPO_ROOT, "models", "gnn", "gnn_edge_congestion.pt")
GNN_DATASET_PATH = os.path.join(_REPO_ROOT, "data", "gnn", "gnn_dataset.pt")
GNN_GRAPH_PATH = os.path.join(_REPO_ROOT, "data", "graph", "toronto_drive_graph.json")


def _pin_inference_device_cpu(payload) -> None:
    """Pin an xgboost model to CPU for inference (in place, best-effort).

    The model may have been trained on the GX10 with ``device="cuda"``. We feed
    it CPU numpy arrays at predict time, so leaving it on cuda forces a slow
    per-call host->device fallback copy (and a warning). Inference is local and
    tiny here, so CPU is both faster and more deterministic. No-op for non-xgboost
    models / when the param isn't present.
    """
    model = payload.get("model") if isinstance(payload, dict) else payload
    if model is None or not hasattr(model, "get_params") or not hasattr(model, "set_params"):
        return
    try:
        if str(model.get_params().get("device", "")).startswith("cuda"):
            model.set_params(device="cpu")
            try:
                model.get_booster().set_param({"device": "cpu"})
            except Exception:  # noqa: BLE001 — booster not materialized yet
                pass
    except Exception:  # noqa: BLE001 — non-xgboost estimator, etc.
        pass


def load_demand_model(model_path: str = MODEL_PATH, kind: str = "auto"):
    """Load a demand model payload.

    ``kind``: ``auto``/``xgboost`` loads the trained tabular model (or the
    heuristic fallback); ``gnn`` selects the GraphSAGE edge model so it can be
    used *anywhere xgboost is* — ``predict_node_demand`` dispatches on the
    payload's ``kind`` and falls back to xgboost if torch/PyG is unavailable.
    """
    # One-switch override: FLOWTO_DEMAND_MODEL=gnn flips every call site to the
    # GNN without code changes (same as xgboost, everywhere). Explicit kind wins.
    if kind == "auto":
        kind = os.environ.get("FLOWTO_DEMAND_MODEL", "xgboost").lower()
    # The payload is treated read-only by predict_node_demand, so it's safe to
    # cache: a full-day fill (24 hourly calls) then loads the pickle once, not
    # 24×. Keyed on (model_path, resolved kind).
    return _load_demand_model_cached(model_path, kind)


@functools.lru_cache(maxsize=8)
def _load_demand_model_cached(model_path: str, kind: str):
    if kind == "gnn":
        return {
            "kind": "gnn",
            "model_path": GNN_MODEL_PATH,
            "dataset_path": GNN_DATASET_PATH,
            "graph_path": GNN_GRAPH_PATH,
            "feature_order": FEATURE_ORDER,
        }
    if os.path.exists(model_path):
        import joblib

        try:
            payload = joblib.load(model_path)
            _pin_inference_device_cpu(payload)
            from .contract import check_compatible

            problems = check_compatible(payload, expected_feature_order=FEATURE_ORDER)
            if problems:
                import warnings

                warnings.warn(
                    "loaded demand model has compatibility issues:\n  - " + "\n  - ".join(problems),
                    RuntimeWarning,
                    stacklevel=2,
                )
            return payload
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


def _predict_node_demand_gnn(graph, model, time_context: dict) -> Dict[object, float]:
    """Run the GraphSAGE edge model and aggregate to per-node demand.

    The GNN predicts per-edge load; node demand is the throughput leaving each
    node = sum of its outgoing edges' predicted load (matching the ``outgoing``
    label strategy the model was trained with). Requires torch + PyG; raises if
    unavailable so the caller can fall back to xgboost.
    """
    import sys

    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    from models.gnn.gnn_to_sim_adapter import predict_gnn_edge_state

    edge_state = predict_gnn_edge_state(
        graph=graph,
        time_context=time_context,
        model_path=model["model_path"],
        dataset_path=model["dataset_path"],
        graph_path=model["graph_path"],
    )

    demand: Dict[object, float] = {}
    for u, _v, data in graph.edges(data=True):
        st = edge_state.get(str(data.get("edge_id")))
        if st:
            demand[u] = demand.get(u, 0.0) + max(float(st.get("predicted_load", 0.0)), 0.0)
    return demand


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

    The static node features (lat/lon/degree/distance/near-highway/class-rank)
    depend only on the graph, so we compute them and assemble the feature matrix
    once and cache it; per-call prediction just overwrites the five time columns.
    Keyed on graph identity + (n_nodes, n_edges) so add/remove mutations
    invalidate the cache (status-only closures don't change these features).
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
    bare sklearn estimator, a `HeuristicDemandModel`, or the GNN payload
    (``kind="gnn"``) — in which case the GraphSAGE edge model drives demand.
    """
    if isinstance(model, dict) and str(model.get("kind", "")).lower() == "gnn":
        try:
            return _predict_node_demand_gnn(graph, model, time_context)
        except Exception as exc:  # noqa: BLE001 — torch/PyG unavailable, etc.
            import warnings

            warnings.warn(
                f"GNN demand unavailable ({exc!r}); falling back to xgboost.",
                RuntimeWarning,
                stacklevel=2,
            )
            model = load_demand_model()

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
