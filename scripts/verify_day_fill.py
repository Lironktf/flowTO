"""Real-graph verification of the day-compute fill (Phase 7).

Boots the full Toronto graph, fills the default view's 24-hour series on the
DayCompute pool, and checks: (a) every hour ends up cached, (b) the demand model
loads exactly once across the whole fill, (c) wall-clock for first-hour-ready and
full-day. Run: .venv/bin/python scripts/verify_day_fill.py
"""

from __future__ import annotations

import os
import time

# Mirror run_api.sh: keep each parallel sim single-threaded so 16 workers use 16
# cores instead of oversubscribing (must be set before numpy import).
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

from torontosim.api._bootstrap import load_default_state  # noqa: E402
from torontosim.api.daycompute import DayCompute, base_time_context, hour_order  # noqa: E402
from torontosim.api import recompute as rc  # noqa: E402
from torontosim.model import predict_node_demand as pnd  # noqa: E402

t0 = time.perf_counter()
state = load_default_state()
print(f"graph loaded in {time.perf_counter() - t0:.1f}s  edges={len(state.edge_ids):,}")

pnd._load_demand_model_cached.cache_clear()

dc = DayCompute(state)
model_kind = "xgboost"
base_tc = base_time_context({"day_of_week": 4, "month": 6})
order = hour_order(8)

# Submit all 24 hours (current first) and time completions.
start = time.perf_counter()
futs = {dc.pool.submit(dc.compute_hour, model_kind, base_tc, [], h, 4): h for h in order}

first_done = None
done = 0
from concurrent.futures import as_completed  # noqa: E402

for fut in as_completed(futs):
    h, res = fut.result()
    done += 1
    if first_done is None:
        first_done = time.perf_counter() - start
        print(f"first hour ready (h={h}) in {first_done:.1f}s  model_actual={res['model_actual']}")
    print(f"  [{done:2d}/24] h={h:2d}  cached_on_return={res['cached']}  avg_p={res['summary'].get('average_pressure'):.4f}")

full = time.perf_counter() - start
print(f"\nFULL DAY: {full:.1f}s  (first hour {first_done:.1f}s)")

# (a) every hour cached now
all_cached = all(dc.is_hour_cached(model_kind, base_tc, [], h) for h in range(24))
# (b) the demand pickle loaded once across the whole fill
ci = pnd._load_demand_model_cached.cache_info()
print(f"all 24 hours cached: {all_cached}")
print(f"load_demand_model cache_info: {ci}  -> loaded once: {ci.misses == 1}")
