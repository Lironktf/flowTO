#!/usr/bin/env python3
"""LOCATION: models/gnn/build_gnn_dataset.py  (load_split)

Loads GNN training labels: read the label CSV, head(max_rows), then iterate
rows via to_dict("records"), checking columns with notna(). Operations copied
from load_split(). No label CSV ships in the repo, so prepare() synthesizes one
with the expected schema under benchmarks/_data/.

This is the interesting counter-example: the real work is a python per-row
loop, which is host-bound. cuDF has to copy the frame back to the host to
iterate, so the GPU can only help the read_csv/head, not the loop.
"""
from __future__ import annotations

import csv
import os

from _harness import finalize, main, stage

_BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(_BENCH_DIR, "_data")
CSV = os.path.join(OUT_DIR, "gnn_labels_synth.csv")
N_ROWS = 120_000
MAX_ROWS = 100_000  # the load_split max_rows cap


def safe_float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def prepare():
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(CSV):
        return
    cols = ["edge_id", "node_id", "vehicle_count", "hour", "day_of_week",
            "month", "is_weekend", "weather", "temperature_c", "precipitation_mm"]
    weathers = ["clear", "cloudy", "rain", "snow"]
    s = 999
    with open(CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for i in range(N_ROWS):
            s = (1103515245 * s + 12345) & 0x7FFFFFFF
            w.writerow([
                f"e{i % 8000}", i % 6000, (s % 900) + 5, i % 24, i % 7,
                (i % 12) + 1, int((i % 7) >= 5), weathers[s % 4],
                round(-10 + (s % 350) / 10, 1), round((s % 50) / 10, 1),
            ])


def pipeline(xp, sync):
    t = {}
    with stage(t, "read_csv", sync):
        df = xp.read_csv(CSV)
    with stage(t, "head", sync):
        df = df.head(MAX_ROWS)

    import pandas as _pd
    notna = _pd.notna  # the loop is host-side python regardless of backend
    with stage(t, "to_dict+iterate", sync):
        # cuDF has no to_dict('records'); the host hop the python loop needs is
        # the honest cost. pandas iterates in place.
        records = (df.to_pandas() if xp.__name__ == "cudf" else df).to_dict("records")
        has_edge_id = "edge_id" in df.columns
        kept = 0
        for row in records:
            if has_edge_id and notna(row.get("edge_id")):
                _ = str(row["edge_id"])
            count = safe_float(row.get("vehicle_count"), 0.0)
            _tc = (row.get("hour", 17), row.get("day_of_week", 4), row.get("month", 6))
            if count > 0:
                kept += 1

    return finalize(t), f"{len(records):,} rows iterated, {kept:,} kept"


TITLE = "build_gnn_dataset.py : load_split (read CSV + per-row python loop)"

if __name__ == "__main__":
    main(TITLE, pipeline, prepare=prepare)
