#!/usr/bin/env python3
"""End-to-end: does the cuDF acceleration actually help the real model pipeline?

Runs the genuine entry points — build_dataset (ingest) and the demand-model
train — twice each: once with cuDF enabled (default), once with cuDF forced off
(monkeypatching cudf_or_none -> None, i.e. the pandas fallback). Reports total
wall time so the GPU data-loading win is measured against the unchanged CPU work
that surrounds it (KD-tree snapping, weather join, sklearn fit).
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import torontosim.model.ingest_real_data as ing
import torontosim.model.train_demand_model as tdm

_REAL_CUDF = ing.cudf_or_none


def _set_cudf(on: bool):
    fn = _REAL_CUDF if on else (lambda: None)
    ing.cudf_or_none = fn
    tdm.cudf_or_none = fn


def timed(label, fn):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    print(f"  >> {label}: {dt:.2f}s")
    return dt, out


def main():
    print("\n### INGEST (build_dataset: load_tmc + groupby + snap + weather)")
    res = {}
    for on in (False, True):  # cold-cache pandas first, then GPU
        _set_cudf(on)
        tag = "cuDF ON " if on else "cuDF OFF"
        dt, df = timed(f"build_dataset [{tag}]", lambda: ing.build_dataset())
        res[on] = (dt, len(df))
    print(f"  rows: OFF={res[False][1]:,}  ON={res[True][1]:,}  "
          f"(match={res[False][1]==res[True][1]})")
    print(f"  INGEST speedup (OFF/ON): {res[False][0]/res[True][0]:.2f}x")

    print("\n### TRAIN (_load_xy -> sklearn fit)")
    tr = {}
    for on in (False, True):
        _set_cudf(on)
        tag = "cuDF ON " if on else "cuDF OFF"
        dt, _ = timed(
            f"train_demand_model [{tag}]",
            lambda: tdm.train_demand_model(
                tdm.TRAINING_CSV, tdm.MODEL_PATH, backend=None, val_path=tdm.VALIDATION_CSV
            ),
        )
        tr[on] = dt
    print(f"  TRAIN speedup (OFF/ON): {tr[False]/tr[True]:.2f}x")

    print("\n### SUMMARY")
    print(f"  ingest: pandas {res[False][0]:.2f}s -> cuDF {res[True][0]:.2f}s "
          f"({res[False][0]/res[True][0]:.2f}x)")
    print(f"  train : pandas {tr[False]:.2f}s -> cuDF {tr[True]:.2f}s "
          f"({tr[False]/tr[True]:.2f}x)")


if __name__ == "__main__":
    main()
