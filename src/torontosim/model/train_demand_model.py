"""
Train the baseline car-demand model.

What it predicts:  location + time/date/weather + road context -> vehicle_count
What it does NOT do:  reason about closed/added roads. That is the job of the
routing + propagation engine. This model only answers "how much traffic *wants*
to exist here, normally, at this time?".

Pipeline:
    training_dataset.csv  --(FEATURE_ORDER)-->  gradient-boosted regressor
    -> models/demand_model.pkl

Data sources:
  * REAL: run `python -m src.model.ingest_real_data` to build
    training_dataset.csv + validation_dataset.csv from Toronto TMC counts +
    ECCC weather (see that module / scripts/fetch_data.sh).
  * SYNTHETIC fallback: `generate_synthetic_training_data` builds a
    Toronto-plausible dataset from the road graph so the pipeline runs even
    with no real data yet.

CLI:
    python -m src.model.train_demand_model --generate          # synthetic CSV
    python -m src.model.train_demand_model --train             # train
    python -m src.model.train_demand_model --train --val data/model/validation_dataset.csv
    python -m src.model.train_demand_model --sweep --backend xgboost --trials 60
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Optional

import numpy as np
import pandas as pd

from .features import (
    FEATURE_ORDER,
    ROAD_CLASS_RANK,
    compute_static_node_features,
    rush_factor,
    weather_code,
)

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
TRAINING_CSV = os.path.join(_REPO_ROOT, "data", "model", "training_dataset.csv")
VALIDATION_CSV = os.path.join(_REPO_ROOT, "data", "model", "validation_dataset.csv")
MODEL_PATH = os.path.join(_REPO_ROOT, "models", "demand_model.pkl")
SWEEP_LOG = os.path.join(_REPO_ROOT, "models", "sweep_results.json")
GRAPH_JSON = os.path.join(_REPO_ROOT, "data", "graph", "toronto_drive_graph.json")

WEATHERS = ["clear", "cloud", "rain", "snow", "fog"]


# ---------------------------------------------------------------------------
# Synthetic, Toronto-plausible training data (fallback when no real counts).
# ---------------------------------------------------------------------------

def _synthetic_count(static_feat: dict, tc: dict, rng: np.random.Generator) -> float:
    """A realistic-looking vehicle count as a function of the features.

    Encodes the same intuitions the README describes (rush hour, downtown pull,
    arterial/highway roads carry more, weather dampens). The model then *learns*
    these relationships; swapping in real counts replaces this with ground
    truth without changing anything else.
    """
    base = 300.0
    rank = static_feat["road_class_rank"]
    class_factor = {6: 3.2, 5: 2.6, 4: 1.9, 3: 1.35, 2: 0.9, 1: 0.5}.get(rank, 0.5)
    downtown_factor = 1.0 + 2.0 * math.exp(-static_feat["distance_to_downtown"] / 4.0)
    highway_factor = 1.3 if static_feat["near_highway"] else 1.0
    degree_factor = 1.0 + 0.05 * max(0, static_feat["road_degree"] - 2)
    rush = rush_factor(tc["hour"], tc["is_weekend"])
    weather_factor = {0: 1.0, 1: 1.0, 2: 0.92, 3: 0.8}.get(weather_code(tc["weather"]), 1.0)

    mean = (base * class_factor * downtown_factor * highway_factor
            * degree_factor * rush * weather_factor)
    noise = rng.lognormal(mean=0.0, sigma=0.18)
    return max(0.0, mean * noise)


def generate_synthetic_training_data(
    graph,
    out_path: str = TRAINING_CSV,
    n_rows: int = 40000,
    seed: int = 42,
) -> str:
    """Generate a synthetic training CSV from the road graph. Returns the path."""
    rng = np.random.default_rng(seed)
    static = compute_static_node_features(graph)
    node_ids = list(static.keys())
    if not node_ids:
        raise ValueError("graph has no featurisable nodes")

    rows = []
    for _ in range(n_rows):
        node = node_ids[rng.integers(0, len(node_ids))]
        sf = static[node]
        hour = int(rng.integers(0, 24))
        dow = int(rng.integers(0, 7))
        month = int(rng.integers(1, 13))
        is_weekend = 1 if dow >= 5 else 0
        weather = WEATHERS[rng.integers(0, len(WEATHERS))]
        tc = {"hour": hour, "day_of_week": dow, "month": month,
              "is_weekend": is_weekend, "weather": weather}
        count = _synthetic_count(sf, tc, rng)
        rows.append({
            "node_id": node,
            "lat": sf["lat"],
            "lon": sf["lon"],
            "hour": hour,
            "day_of_week": dow,
            "month": month,
            "is_weekend": is_weekend,
            "weather": weather,
            "weather_code": weather_code(weather),
            "road_degree": sf["road_degree"],
            "distance_to_downtown": sf["distance_to_downtown"],
            "near_highway": sf["near_highway"],
            "road_class_rank": sf["road_class_rank"],
            "vehicle_count": round(count, 1),
        })

    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"  wrote {out_path}  ({len(df):,} rows, "
          f"vehicle_count mean={df['vehicle_count'].mean():.0f})")
    return out_path


# ---------------------------------------------------------------------------
# Data loading shared by train + sweep
# ---------------------------------------------------------------------------

def _load_xy(path: str):
    df = pd.read_csv(path)
    if "weather_code" not in df.columns and "weather" in df.columns:
        df["weather_code"] = df["weather"].map(weather_code).fillna(0).astype(int)
    missing = [c for c in FEATURE_ORDER if c not in df.columns]
    if missing:
        raise ValueError(f"CSV {path} missing feature columns: {missing}")
    if "vehicle_count" not in df.columns:
        raise ValueError(f"CSV {path} missing target column 'vehicle_count'")
    X = df[FEATURE_ORDER].to_numpy(dtype=float)
    y = df["vehicle_count"].to_numpy(dtype=float)
    return X, y


def _train_val_arrays(training_data_path: str, val_path: Optional[str]):
    """Return (X_tr, X_te, y_tr, y_te). Uses an explicit val CSV if given,
    otherwise a random 80/20 split of the training CSV."""
    X, y = _load_xy(training_data_path)
    if val_path and os.path.exists(val_path):
        X_te, y_te = _load_xy(val_path)
        print(f"  using explicit validation set: {len(X_te):,} rows ({val_path})")
        return X, X_te, y, y_te
    from sklearn.model_selection import train_test_split
    return train_test_split(X, y, test_size=0.2, random_state=42)


# ---------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------

def _make_estimator(backend: str, params: Optional[dict] = None):
    """Return (estimator, kind). backend: 'sklearn' or 'xgboost'.

    'xgboost' uses the GPU when available (device='cuda') — useful on an
    NVIDIA box like the ASUS GX10. Falls back to sklearn if xgboost is absent.
    Use 'xgboost-cpu' to force the CPU build. `params` overrides defaults.
    """
    params = params or {}
    if backend in ("xgboost", "xgboost-gpu", "gpu", "xgboost-cpu"):
        try:
            from xgboost import XGBRegressor
        except ImportError:
            print("  [backend] xgboost not installed; falling back to sklearn")
        else:
            device = "cpu" if backend == "xgboost-cpu" else "cuda"
            defaults = dict(n_estimators=600, learning_rate=0.05, max_depth=8,
                            subsample=0.9, colsample_bytree=0.9, reg_lambda=1.0,
                            tree_method="hist", device=device, random_state=42)
            defaults.update(params)
            return XGBRegressor(**defaults), f"XGBRegressor(device={device})"
    from sklearn.ensemble import HistGradientBoostingRegressor
    defaults = dict(max_iter=400, learning_rate=0.06, max_depth=8,
                    l2_regularization=1.0, random_state=42)
    defaults.update(params)
    return HistGradientBoostingRegressor(**defaults), "HistGradientBoostingRegressor"


def _save(model, kind, mae, r2, model_path, extra=None):
    import joblib
    payload = {
        "model": model,
        "feature_order": FEATURE_ORDER,
        "target": "vehicle_count",
        "kind": kind,
        "metrics": {"mae": float(mae), "r2": float(r2)},
    }
    if extra:
        payload.update(extra)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    joblib.dump(payload, model_path)
    print(f"  saved {model_path}")


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_demand_model(
    training_data_path: str = TRAINING_CSV,
    model_path: str = MODEL_PATH,
    backend: Optional[str] = None,
    val_path: Optional[str] = None,
):
    """Train the demand model from a CSV and persist it. Returns the estimator.

    `backend`: 'sklearn' (default) or 'xgboost' (GPU if available); also
    settable via FLOWTO_MODEL_BACKEND. `val_path`: optional held-out CSV; if
    omitted, an 80/20 split of the training CSV is used for the holdout score.
    """
    backend = (backend or os.environ.get("FLOWTO_MODEL_BACKEND", "sklearn")).lower()
    from sklearn.metrics import mean_absolute_error, r2_score

    X_tr, X_te, y_tr, y_te = _train_val_arrays(training_data_path, val_path)
    model, kind = _make_estimator(backend)
    model.fit(X_tr, y_tr)

    pred = model.predict(X_te)
    mae = mean_absolute_error(y_te, pred)
    r2 = r2_score(y_te, pred)
    print(f"  trained {kind} on {len(X_tr):,} rows")
    print(f"  holdout MAE={mae:.1f} vehicles, R^2={r2:.3f}")

    _save(model, kind, mae, r2, model_path)
    return model


# ---------------------------------------------------------------------------
# Overnight hyper-parameter sweep (designed for the GX10 + GPU xgboost)
# ---------------------------------------------------------------------------

# Random search space. Wide enough to keep a GPU busy for a while overnight.
_SWEEP_SPACE = {
    "n_estimators": [400, 600, 900, 1200, 1600, 2000],
    "learning_rate": [0.02, 0.03, 0.05, 0.08, 0.1],
    "max_depth": [5, 6, 7, 8, 10, 12],
    "subsample": [0.7, 0.8, 0.9, 1.0],
    "colsample_bytree": [0.7, 0.8, 0.9, 1.0],
    "reg_lambda": [0.5, 1.0, 2.0, 5.0],
    "min_child_weight": [1, 3, 5, 10],
}


def train_with_sweep(
    training_data_path: str = TRAINING_CSV,
    val_path: Optional[str] = VALIDATION_CSV,
    model_path: str = MODEL_PATH,
    backend: str = "xgboost",
    trials: int = 60,
    seed: int = 42,
    log_path: str = SWEEP_LOG,
):
    """Randomised hyper-parameter search, picking the best by validation MAE.

    Logs every trial to `log_path` and saves the single best model to
    `model_path`. Uses early stopping on the validation set when xgboost is
    available, so big n_estimators don't overfit or waste time.
    """
    from sklearn.metrics import mean_absolute_error, r2_score

    X_tr, X_te, y_tr, y_te = _train_val_arrays(training_data_path, val_path)
    rng = np.random.default_rng(seed)

    have_xgb = False
    if backend.startswith("xgboost") or backend == "gpu":
        try:
            import xgboost  # noqa: F401
            have_xgb = True
        except ImportError:
            print("  [sweep] xgboost missing; sweeping sklearn instead")
            backend = "sklearn"

    results = []
    best = {"mae": math.inf}
    print(f"  sweeping {trials} trials  (backend={backend})")
    for t in range(trials):
        if have_xgb:
            params = {k: _pick(rng, v) for k, v in _SWEEP_SPACE.items()}
        else:
            params = {
                "max_iter": int(_pick(rng, _SWEEP_SPACE["n_estimators"])),
                "learning_rate": float(_pick(rng, _SWEEP_SPACE["learning_rate"])),
                "max_depth": int(_pick(rng, _SWEEP_SPACE["max_depth"])),
                "l2_regularization": float(_pick(rng, _SWEEP_SPACE["reg_lambda"])),
            }
        model, kind = _make_estimator(backend, params)
        try:
            if have_xgb:
                model.set_params(early_stopping_rounds=40)
                model.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)
            else:
                model.fit(X_tr, y_tr)
        except Exception as e:  # noqa: BLE001
            print(f"   trial {t}: FAILED ({e})")
            continue

        pred = model.predict(X_te)
        mae = float(mean_absolute_error(y_te, pred))
        r2 = float(r2_score(y_te, pred))
        results.append({"trial": t, "mae": mae, "r2": r2, "params": params})
        marker = ""
        if mae < best["mae"]:
            best = {"mae": mae, "r2": r2, "params": params,
                    "model": model, "kind": kind}
            marker = "  <-- best"
            _save(model, kind, mae, r2, model_path,
                  extra={"hyperparameters": params, "sweep_trial": t})
        print(f"   trial {t:>3}: MAE={mae:8.1f}  R^2={r2:.3f}{marker}")

        # Persist the running log after each trial (resumable / inspectable).
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as fh:
            json.dump({"backend": backend, "trials": results,
                       "best": {k: best[k] for k in ("mae", "r2", "params")
                                if k in best}}, fh, indent=1)

    print(f"\n  BEST: MAE={best['mae']:.1f}  R^2={best.get('r2', float('nan')):.3f}")
    print(f"  best params: {best.get('params')}")
    print(f"  full log -> {log_path}")
    return best.get("model")


def _pick(rng, choices):
    return choices[int(rng.integers(0, len(choices)))]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_graph():
    from ..graph.routing import import_graph_json
    return import_graph_json(GRAPH_JSON)


def main(argv=None):
    p = argparse.ArgumentParser(description="Train the Toronto demand model.")
    p.add_argument("--generate", action="store_true",
                   help="(Re)generate the synthetic training CSV from the graph.")
    p.add_argument("--train", action="store_true", help="Train from the CSV.")
    p.add_argument("--sweep", action="store_true",
                   help="Run an overnight hyper-parameter sweep (GX10/GPU friendly).")
    p.add_argument("--trials", type=int, default=60, help="Sweep trial count.")
    p.add_argument("--rows", type=int, default=40000, help="Synthetic row count.")
    p.add_argument("--csv", default=TRAINING_CSV)
    p.add_argument("--val", default=None,
                   help="Validation CSV (default: validation_dataset.csv if present).")
    p.add_argument("--out", default=MODEL_PATH)
    p.add_argument("--backend", default=None,
                   help="Learner: 'sklearn' (default) or 'xgboost' (GPU if available).")
    args = p.parse_args(argv)

    val = args.val
    if val is None and os.path.exists(VALIDATION_CSV):
        val = VALIDATION_CSV

    if args.generate:
        print("Generating synthetic training data ...")
        generate_synthetic_training_data(_load_graph(), args.csv, n_rows=args.rows)

    if args.sweep:
        print("Running hyper-parameter sweep ...")
        train_with_sweep(args.csv, val_path=val, model_path=args.out,
                         backend=(args.backend or "xgboost"), trials=args.trials)
        return

    # Default with no action flags: generate-if-missing then train.
    do_train = args.train or not args.generate
    if not args.generate and not os.path.exists(args.csv):
        print("Generating synthetic training data (no CSV present) ...")
        generate_synthetic_training_data(_load_graph(), args.csv, n_rows=args.rows)
    if do_train:
        print("Training demand model ...")
        train_demand_model(args.csv, args.out, backend=args.backend, val_path=val)


if __name__ == "__main__":
    main()
