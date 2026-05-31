"""Shared timing harness for the pandas-vs-cuDF location benchmarks.

Every ``bench_*.py`` in this directory mirrors the pandas operations from one
real call-site in the repo and exposes a single ``pipeline(xp, sync)`` function.
``xp`` is the DataFrame module (``pandas`` or ``cudf``) — because cuDF mirrors
the pandas API, the *same* pipeline body runs on both, so the timings compare
like for like. This module runs that pipeline on each backend, with a warm-up
run (CUDA context / file cache) excluded from the timed average, and prints a
per-stage table plus the CPU/GPU speedup.
"""
from __future__ import annotations

import argparse
import contextlib
import time


@contextlib.contextmanager
def stage(timings: dict, name: str, sync=None):
    """Time one pipeline stage. ``sync`` (if given) flushes the GPU first and
    after so async kernels are actually accounted to this stage."""
    if sync is not None:
        sync()
    t0 = time.perf_counter()
    yield
    if sync is not None:
        sync()
    timings[name] = timings.get(name, 0.0) + (time.perf_counter() - t0)


def finalize(timings: dict) -> dict:
    """Add a TOTAL = sum of all stages, so each pipeline doesn't repeat it."""
    timings["TOTAL"] = sum(v for k, v in timings.items() if k != "TOTAL")
    return timings


def gpu_sync():
    """Return a CUDA device-synchronize callable, or None if cupy is absent."""
    try:
        import cupy
        return cupy.cuda.runtime.deviceSynchronize
    except Exception:
        return None


def _avg(runs: list[dict]) -> dict:
    keys = list(runs[0].keys())
    return {k: sum(r[k] for r in runs) / len(runs) for k in keys}


def _bench_backend(xp, label, pipeline, repeats, sync) -> dict:
    print(f"\n=== {label} ===")
    warm, info = pipeline(xp, sync)
    print(f"warm-up: {warm['TOTAL'] * 1000:8.1f} ms   {info}")
    runs = [pipeline(xp, sync)[0] for _ in range(repeats)]
    avg = _avg(runs)
    for k in avg:
        if k == "TOTAL":
            continue
        print(f"  {k:<24}{avg[k] * 1000:9.2f} ms")
    print(f"  {'TOTAL':<24}{avg['TOTAL'] * 1000:9.2f} ms")
    return avg


def run(pipeline, *, title, repeats=3, backends=("pandas", "cudf")) -> tuple[dict, dict]:
    print(f"\n{'#' * 70}\n# {title}\n{'#' * 70}")
    pd_avg = cudf_avg = None
    if "pandas" in backends:
        import pandas as pd
        pd_avg = _bench_backend(pd, f"pandas {pd.__version__} (CPU)", pipeline, repeats, None)
    if "cudf" in backends:
        import cudf
        cudf_avg = _bench_backend(
            cudf, f"cuDF {cudf.__version__} (GPU)", pipeline, repeats, gpu_sync()
        )
    if pd_avg and cudf_avg:
        print("\n--- speedup (pandas time / cuDF time, >1 means GPU wins) ---")
        for k in pd_avg:
            if cudf_avg.get(k, 0) > 0:
                sp = pd_avg[k] / cudf_avg[k]
                flag = "" if sp >= 1 else "   <- cuDF slower"
                print(f"  {k:<24}{sp:7.1f}x{flag}")
    return pd_avg, cudf_avg


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--backend", choices=["both", "pandas", "cudf"], default="both")
    return p.parse_args()


def main(title, pipeline, prepare=None):
    """Entry point for running a single bench_*.py directly."""
    args = parse_args()
    if prepare is not None:
        prepare()
    backends = ("pandas", "cudf") if args.backend == "both" else (args.backend,)
    return run(pipeline, title=title, repeats=args.repeats, backends=backends)
