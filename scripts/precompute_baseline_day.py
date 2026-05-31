"""Precompute the GNN baseline day (24 hours, full coverage) to disk.

The no-edit baseline view is the GNN's per-edge pressure prediction for every edge.
A whole day is only ~0.3s once the 175 MB tensor bundle is loaded, so this is mostly
about persisting the default day to a .bin artifact that /baseline/predicted serves
instantly at cold start (before the startup warm finishes) and across restarts.

Usage:
    .venv/bin/python scripts/precompute_baseline_day.py          # default Wed/June
    .venv/bin/python scripts/precompute_baseline_day.py 2 6      # dow month
"""

from __future__ import annotations

import os
import sys
import time

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from torontosim.api import gnn_baseline as gb  # noqa: E402
from torontosim.api._bootstrap import load_default_state  # noqa: E402


def main() -> None:
    dow = int(sys.argv[1]) if len(sys.argv) > 1 else gb.DEFAULT_DOW
    month = int(sys.argv[2]) if len(sys.argv) > 2 else gb.DEFAULT_MONTH

    t0 = time.perf_counter()
    state = load_default_state()
    print(f"graph loaded in {time.perf_counter() - t0:.1f}s  edges={len(state.edge_ids):,}")

    t0 = time.perf_counter()
    gb.get_bundle()  # one-time 175 MB dataset + model load
    print(f"GNN bundle loaded in {time.perf_counter() - t0:.1f}s")

    t0 = time.perf_counter()
    day = gb.day_records(state, dow, month)
    dt = time.perf_counter() - t0
    active = [sum(1 for r in h if r[3] > 0) for h in day]
    print(f"computed 24h GNN day (dow={dow} month={month}) in {dt:.2f}s")
    print(f"  coverage: {len(day[0]):,} edges/hour, active(pressure>0) min={min(active):,} max={max(active):,}")

    path = gb.write_artifact(state, dow, month)
    print(f"wrote {path}  ({os.path.getsize(path) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
