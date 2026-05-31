#!/usr/bin/env python3
"""LOCATION: torontosim/model/train_demand_model.py  (_load_xy)

Loads the model training matrix: read the training CSV, ensure a weather_code
column (map from the 'weather' string when missing), select FEATURE_ORDER and
the target, and convert to NumPy for sklearn/xgboost. Operations copied from
_load_xy().
"""
from __future__ import annotations

import os

from _harness import finalize, main, stage

# --- copied from torontosim/model/features.py ------------------------------
FEATURE_ORDER = [
    "lat", "lon", "hour", "day_of_week", "month", "is_weekend",
    "weather_code", "road_degree", "distance_to_downtown",
    "near_highway", "road_class_rank",
]
WEATHER_CODE = {"clear": 0, "cloudy": 1, "rain": 2, "snow": 3, "fog": 4}
DEFAULT_WEATHER_CODE = 0
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(_REPO_ROOT, "data", "model", "training_dataset.csv")


def pipeline(xp, sync):
    t = {}
    with stage(t, "read_csv", sync):
        df = xp.read_csv(CSV)

    # _load_xy maps weather->weather_code only when the column is missing.
    # weather_code is a pure string->int lookup, so a dict map is equivalent
    # on both backends (cuDF Series.map takes a dict; a python callable would
    # need a UDF). Force-exercise it here to time the real fallback path.
    with stage(t, "weather_code_map", sync):
        codes = df["weather"].map(WEATHER_CODE).fillna(DEFAULT_WEATHER_CODE).astype("int32")
        df["weather_code"] = codes

    with stage(t, "select_features", sync):
        feats = df[FEATURE_ORDER]
        target = df["vehicle_count"]
    with stage(t, "to_numpy", sync):
        X = feats.to_numpy(dtype="float64")
        y = target.to_numpy(dtype="float64")

    return finalize(t), f"X={X.shape}, y={y.shape}"


TITLE = "train_demand_model.py : _load_xy (read CSV -> feature matrix)"

if __name__ == "__main__":
    main(TITLE, pipeline)
