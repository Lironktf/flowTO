#!/usr/bin/env python3
"""Zero-code-change accelerator benchmark: stock pandas vs `cudf.pandas`.

This reuses the EXACT same per-location ``pipeline(xp, sync)`` functions as the
explicit-cuDF suite (bench_ingest_tmc, bench_load_xy, ...). Here we always pass
the ``pandas`` module as ``xp`` and only change how pandas itself executes:

    # CPU baseline (stock pandas)
    .venv/bin/python benchmarks/bench_cudf_pandas.py
    # GPU-accelerated, zero code change
    .venv/bin/python -m cudf.pandas benchmarks/bench_cudf_pandas.py

`cudf.pandas` patches the pandas module before import and runs ops on the GPU
with automatic CPU fallback. Because the pipeline bodies are identical to the
ones run_all.py feeds to stock pandas, the "stock pandas" column here matches
run_all.py's pandas column — there is now ONE fixed pandas baseline shared
across both suites. The only variable is the execution backend.

Use run_cudf_pandas.py to run both passes and print the comparison. Lines
prefixed ``RESULT\t`` are machine-parseable totals for that runner.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402  (may be patched by `python -m cudf.pandas`)

import bench_gnn_labels  # noqa: E402
import bench_ingest_tmc  # noqa: E402
import bench_load_xy  # noqa: E402
import bench_odme_counts  # noqa: E402
import bench_synthetic_write  # noqa: E402

# Same five call-sites, same shared pipeline functions as run_all.py.
MODULES = [
    bench_ingest_tmc,
    bench_load_xy,
    bench_odme_counts,
    bench_synthetic_write,
    bench_gnn_labels,
]


def accelerator_active() -> bool:
    return ("cudf.pandas" in sys.modules
            or "cudf" in type(pd.Series(dtype="float64")).__module__)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    mode = "cudf.pandas (GPU)" if accelerator_active() else "stock pandas (CPU)"
    print(f"\n### MODE: {mode}  |  pandas {pd.__version__}  |  repeats={args.repeats}")
    print(f"{'location':<52}{'avg ms':>10}")
    print("-" * 62)

    for mod in MODULES:
        if hasattr(mod, "prepare"):
            mod.prepare()
        # Identical methodology to _harness: one untimed warm-up, then average
        # the pipeline's own TOTAL over `repeats` runs. xp=pd, no GPU sync (the
        # stock-pandas path uses none either, keeping the baseline comparable).
        mod.pipeline(pd, None)
        totals = [mod.pipeline(pd, None)[0]["TOTAL"] for _ in range(args.repeats)]
        avg = sum(totals) / len(totals)
        print(f"{mod.TITLE:<52}{avg * 1000:9.1f}")
        print(f"RESULT\t{mode}\t{mod.TITLE}\t{avg * 1000:.3f}")


if __name__ == "__main__":
    main()
