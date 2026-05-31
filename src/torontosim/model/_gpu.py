"""Optional cuDF (RAPIDS) acceleration with a transparent pandas fallback.

The data-pipeline call-sites use these helpers to run the heavy, vectorisable
parts (CSV read, numeric coercion, datetime parsing, groupby) on the GPU when
cuDF is available, and fall back to the existing pandas path otherwise. The
accelerated paths always convert back to host objects (pandas / numpy) at the
boundary, so downstream code — sklearn, networkx, KD-tree snapping, per-row
loops — is unchanged.

Measured speedups for these sites on an NVIDIA GB10 are in ``benchmarks/``
(≈3.8–6.1× for the read/groupby-heavy ones; the GPU is only installed via the
``[gpu]`` extra, so most environments transparently use pandas).
"""
from __future__ import annotations


def cudf_or_none():
    """Return the ``cudf`` module if importable on this machine, else ``None``."""
    try:
        import cudf
        return cudf
    except Exception:  # noqa: BLE001 — no GPU / RAPIDS not installed
        return None
