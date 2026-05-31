# pandas vs RAPIDS cuDF benchmarks

Each `bench_*.py` mirrors **one real pandas call-site** in the repo and times
the exact same operations on pandas (CPU) and cuDF (GPU). Because cuDF mirrors
the pandas API, a single `pipeline(xp, sync)` body runs on both backends — only
the `xp` module differs. A warm-up run (CUDA context + file cache) is excluded
from the timed average.

Run on an **NVIDIA GB10 (DGX Spark)** with the project venv
(`pandas 2.3.3`, `cudf-cu13 26.04`).

## Layout

| File | Call-site it mirrors | What it does |
|------|----------------------|--------------|
| `bench_ingest_tmc.py` | `model/ingest_real_data.py` `load_tmc` + `build_dataset` | read+concat raw TMC CSVs, numeric coerce, row-sum, datetime parse, dropna, hourly groupby |
| `bench_load_xy.py` | `model/train_demand_model.py` `_load_xy` | read training CSV, weather→code map, select features, `to_numpy` |
| `bench_odme_counts.py` | `model/odme_calibrate.py` `fetch_observed_counts` | read CSV, filter hour/weekend, groupby-mean per node |
| `bench_synthetic_write.py` | `model/train_demand_model.py` `_make_synthetic_dataset` | build DataFrame from generated rows, `to_csv` |
| `bench_gnn_labels.py` | `models/gnn/build_gnn_dataset.py` `load_split` | read CSV, `head`, `to_dict("records")` + per-row python loop |

`_harness.py` is the shared timing/printing harness. `_data/` holds generated
inputs (synthetic GNN labels + CSV outputs); it can be deleted any time.

## Running

```bash
# everything, with a combined summary
.venv/bin/python benchmarks/run_all.py --repeats 3

# one location
.venv/bin/python benchmarks/bench_ingest_tmc.py --repeats 5
.venv/bin/python benchmarks/bench_load_xy.py --backend pandas   # single backend
```

## One shared baseline

Both suites call the **same** per-location `pipeline(xp, sync)` functions
(defined in the `bench_*.py` files). `run_all.py` runs them with `xp=pandas`
and `xp=cudf`; `bench_cudf_pandas.py` runs the identical functions with
`xp=pandas` under stock pandas and again under `python -m cudf.pandas`. So
"stock pandas" is **one fixed code path** measured the same way everywhere —
the only variable is the execution backend. (The two sub-80 ms CSV-read sites
still wander ±30 ms run-to-run from OS file-cache warmth; that's environment
noise, not a code difference. The large sites are stable.)

## Three backends, same code (repeats=3, GB10)

| Location | stock pandas | cuDF (explicit API) | `cudf.pandas` (zero-change) |
|----------|-------------:|--------------------:|----------------------------:|
| `ingest_real_data.py` (load_tmc + groupby) | 925 ms | 181 ms · **5.1×** | 176 ms · **5.1×** |
| `train_demand_model.py` (`_load_xy`) | 76 ms | 20 ms · **3.8×** | 29 ms · **1.6×** |
| `odme_calibrate.py` (`fetch_observed_counts`) | 70 ms | 15 ms · **4.6×** | 36 ms · **1.2×** |
| `train_demand_model.py` (`_make_synthetic_dataset`) | 475 ms | 77 ms · **6.1×** | 865 ms · **0.5×** |
| `build_gnn_dataset.py` (`load_split`) | 160 ms | 152 ms · **1.1×** | 1326 ms · **0.1×** |

- **explicit API** = call-sites rewritten to the cuDF DataFrame API.
- **`cudf.pandas`** = keep `import pandas as pd`, run under
  `python -m cudf.pandas` (patches pandas, runs on GPU with CPU fallback).

```bash
.venv/bin/python benchmarks/run_all.py --repeats 3          # stock pandas vs explicit cuDF
.venv/bin/python benchmarks/run_cudf_pandas.py --repeats 3  # stock pandas vs cudf.pandas
```

### Reading the accelerator column
With GPU-friendly code (this is the same tuned pipeline, not the literal repo
patterns), `cudf.pandas` matches the explicit rewrite **on the heavy ingest
path** — 176 ms vs 181 ms, both ~5.1× — for zero code change. But two sites are
structurally hostile to it:
- **`load_split` (0.1×)** — a `to_dict("records")` + per-row python loop. The
  proxy must materialize every row on the host and wrap each element, so it's
  ~8× *slower*. Inherent to row-wise iteration; the fix is to vectorize the
  loop, not switch backend.
- **`_make_synthetic_dataset` (0.5×)** — building a frame from python lists then
  `to_csv`. Construction from host objects + proxy overhead doesn't pay off at
  this size.
- The small read+select/groupby sites (`_load_xy`, `odme`) net out ahead
  (1.2–1.6×) but below the explicit API, because a chunk of each is host work
  (`to_numpy`, the result-dict build) that the proxy can't accelerate.

**Takeaway:** for the one workload that dominates wall-time (TMC ingest),
`cudf.pandas` gives the full ~5× with no rewrite. The explicit cuDF API wins
clearly on the medium CSV sites and the synthetic build, and is the only option
that helps the row-loop site (by being rewritten to avoid the loop).

## Per-stage takeaways (explicit cuDF API)
- **I/O-heavy CSV work wins big.** `read_csv` is ~5× faster on the GPU parser
  across every location, and `to_csv` is ~34× faster — these dominate the
  totals and drive the speedups.
- **Wide vectorized ops win biggest.** Summing 36 vehicle columns row-wise is
  ~14× faster on GPU.
- **Tiny per-column ops can be slower on GPU.** `to_numeric` on a small set of
  columns and `to_numpy` (a device→host copy) lose to pandas — kernel-launch /
  transfer overhead outweighs the work. Negligible in absolute ms.
- **Per-row python loops don't benefit.** `build_gnn_dataset.load_split`
  iterates with `to_dict("records")`; cuDF must copy back to the host to do
  that, so the loop is the bottleneck on both (~1.0×). The real fix there is to
  vectorize the loop, not to swap the backend.

## End-to-end reality check (does it help the real pipeline?)

`run_model_end_to_end.py` runs the genuine entry points with cuDF on vs forced
off. The micro-benchmark wins **mostly do not survive** end-to-end:

| Pipeline | pandas | cuDF | speedup |
|----------|-------:|-----:|--------:|
| `build_dataset` (ingest, one-shot CLI run) | 5.51 s | 5.93 s | **0.93×** (slightly slower) |
| `train_demand_model` (`_load_xy` + sklearn fit) | 1.46 s | 1.21 s | **1.20×** |

Two effects explain the gap between the 5× micro-benchmark and reality:

1. **Amdahl's law.** `load_tmc` is only ~25% of `build_dataset` (1.36 s of
   5.5 s). The other 75% — `load_weather` (0.93 s, an iterrows loop) and the
   KD-tree node-snapping (~3 s of per-row Python) — is CPU work cuDF doesn't
   touch. So even a perfect GPU read caps the ingest at ~1.2×.
2. **Cold-start tax.** The *first* cuDF call in a process pays ~1 s of CUDA
   context init: `load_tmc` is **1.49 s cold** (slower than pandas' 1.36 s) but
   **0.44 s warm**. A one-shot CLI run only ever sees the cold number, so cuDF
   is a net loss there. `train` shows 1.20× only because the context was already
   warmed by the preceding ingest run.

**Conclusion:** cuDF helps the *isolated data ops* (3–5× warm) but **not the
end-to-end pipeline as it stands** — the loading we accelerated is a minority of
the wall time, and the GPU's per-process warm-up eats the read saving on a
single run. It pays off only when the GPU context is reused across many calls
*and* the workload is dominated by the vectorizable ops (not the CPU snapping /
weather loop / sklearn fit). The fallback makes the change harmless either way.

## Applied to the codebase

These findings were rolled into the real call-sites using the **explicit cuDF
API with a pandas fallback** (the `[gpu]` extra; auto-detected via
`torontosim.model._gpu.cudf_or_none()`, so CPU-only environments are
unaffected). Every accelerated path converts back to host objects
(`to_pandas`/`to_numpy`) at the boundary, so downstream code (sklearn,
networkx, the KD-tree snapper, the per-row loops) is unchanged — and the GPU
output was verified byte-equivalent to the pandas path.

| Source function | Change |
|-----------------|--------|
| `model/ingest_real_data.py::load_tmc` | cuDF read→numeric→datetime→dropna via shared `_finalize_tmc(df, xp, gpu)`; returns pandas |
| `model/train_demand_model.py::_load_xy` | cuDF read+select via `_read_features_df`; `to_numpy` returns host arrays |
| `model/odme_calibrate.py::load_observed_counts` | cuDF read+filter+groupby via `_read_counts`; grouped result moved to host |
| `model/train_demand_model.py::_make_synthetic_dataset` | cuDF build + `to_csv` via `_make_df` (dict-of-columns) |
| `models/gnn/build_gnn_dataset.py::_label_rows_from_csv` | cuDF read only (`_read_labels_csv` → `to_pandas`); per-row loop left on host (by design, ~1.1×) |
