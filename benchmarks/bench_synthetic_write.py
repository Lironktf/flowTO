#!/usr/bin/env python3
"""LOCATION: torontosim/model/train_demand_model.py  (_make_synthetic_dataset)

Builds the synthetic training CSV: assemble a list of per-row dicts, construct
a DataFrame from them, then write to CSV (and a mean() sanity print).
Operations copied from the `df = pd.DataFrame(rows); df.to_csv(...)` tail of
_make_synthetic_dataset(). The python row-generation loop is backend-agnostic,
so it's done once up front (untimed) and only the DataFrame build + write are
timed.
"""
from __future__ import annotations

import os

from _harness import finalize, main, stage

_BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(_BENCH_DIR, "_data")
N_ROWS = 120_000  # ~ the real synthetic training set size

_ROWS = None  # generated once, shared across backends


def _generate_rows(n):
    rng_a = 1103515245
    rows = []
    s = 12345
    for i in range(n):
        s = (rng_a * s + 12345) & 0x7FFFFFFF  # cheap deterministic pseudo-rng
        rows.append({
            "node_id": i % 5000,
            "lat": 43.65 + (s % 1000) / 100000,
            "lon": -79.38 - (s % 800) / 100000,
            "hour": i % 24,
            "day_of_week": i % 7,
            "month": (i % 12) + 1,
            "is_weekend": int((i % 7) >= 5),
            "weather": ["clear", "cloudy", "rain", "snow"][s % 4],
            "weather_code": s % 4,
            "road_degree": (s % 5) + 1,
            "distance_to_downtown": (s % 12000) / 1.0,
            "near_highway": s % 2,
            "road_class_rank": (s % 6) + 1,
            "vehicle_count": round((s % 900) + 10.0, 1),
        })
    return rows


def prepare():
    global _ROWS
    os.makedirs(OUT_DIR, exist_ok=True)
    _ROWS = _generate_rows(N_ROWS)


def pipeline(xp, sync):
    t = {}
    out = os.path.join(OUT_DIR, f"synthetic_{xp.__name__}.csv")

    with stage(t, "DataFrame(rows)", sync):
        # cuDF builds columnar frames from a dict-of-columns, not list-of-dicts;
        # the equivalent, supported construction on both is via column dict.
        cols = {k: [r[k] for r in _ROWS] for k in _ROWS[0]}
        df = xp.DataFrame(cols)
    with stage(t, "mean", sync):
        _ = float(df["vehicle_count"].mean())
    with stage(t, "to_csv", sync):
        df.to_csv(out, index=False)

    return finalize(t), f"{len(df):,} rows -> {os.path.basename(out)}"


TITLE = "train_demand_model.py : _make_synthetic_dataset (build + to_csv)"

if __name__ == "__main__":
    main(TITLE, pipeline, prepare=prepare)
