"""Timing harness (P11): ``@timed`` decorator + ``timer`` context manager.

Collects structured ``(label, duration_ms)`` records into a process-global
registry. Near-zero overhead, deterministic labels, nestable. Uses
``perf_counter`` (wall-clock for perf evidence — never feeds sim determinism).
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager

# Ordered list of timing records for the current process (cleared via reset).
_RECORDS: list[dict] = []


def reset_timings() -> None:
    _RECORDS.clear()


def get_timings() -> list[dict]:
    """All recorded timings in completion order."""
    return list(_RECORDS)


def record(label: str, duration_ms: float, **meta) -> None:
    _RECORDS.append({"label": label, "ms": round(duration_ms, 4), **meta})


@contextmanager
def timer(label: str, **meta):
    """``with timer("solve"): ...`` — records the elapsed ms on exit."""
    start = time.perf_counter()
    try:
        yield
    finally:
        record(label, (time.perf_counter() - start) * 1000.0, **meta)


def timed(label: str | None = None):
    """``@timed("graph_build")`` — record a function's wall time per call."""

    def deco(fn):
        lab = label or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                record(lab, (time.perf_counter() - start) * 1000.0)

        return wrapper

    return deco


def summary() -> dict:
    """Aggregate: per-label count + total + mean ms (deterministic order)."""
    agg: dict = {}
    for r in _RECORDS:
        a = agg.setdefault(r["label"], {"count": 0, "total_ms": 0.0})
        a["count"] += 1
        a["total_ms"] += r["ms"]
    for a in agg.values():
        a["mean_ms"] = round(a["total_ms"] / a["count"], 4) if a["count"] else 0.0
        a["total_ms"] = round(a["total_ms"], 4)
    return dict(sorted(agg.items()))
