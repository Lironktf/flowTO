#!/usr/bin/env python3
"""Run every pandas-vs-cuDF location benchmark and print a combined summary.

    .venv/bin/python benchmarks/run_all.py
    .venv/bin/python benchmarks/run_all.py --repeats 5

Each module mirrors one real pandas call-site in the repo (see its docstring).
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _harness  # noqa: E402

MODULES = [
    "bench_ingest_tmc",
    "bench_load_xy",
    "bench_odme_counts",
    "bench_synthetic_write",
    "bench_gnn_labels",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    summary = []
    for name in MODULES:
        mod = importlib.import_module(name)
        if hasattr(mod, "prepare"):
            mod.prepare()
        pd_avg, cudf_avg = _harness.run(mod.pipeline, title=mod.TITLE, repeats=args.repeats)
        summary.append((mod.TITLE, pd_avg["TOTAL"], cudf_avg["TOTAL"]))

    print(f"\n{'=' * 82}\n COMBINED SUMMARY (total wall time per location)\n{'=' * 82}")
    print(f"{'location':<55}{'pandas':>10}{'cuDF':>10}{'speedup':>8}")
    print("-" * 82)
    for title, pd_t, cudf_t in summary:
        # title is "file.py : func (notes)"; keep "file.py : func"
        loc = title.split("(")[0].strip()
        if len(loc) > 53:
            loc = loc[:52] + "…"
        print(f"{loc:<55}{pd_t * 1000:8.1f}ms{cudf_t * 1000:8.1f}ms{pd_t / cudf_t:7.1f}x")


if __name__ == "__main__":
    main()
