"""Shortest-path backends for the equilibrium AON loading step (P04).

One interface, two implementations:
  * ``cpu``  — heap Dijkstra over the CSR (always available, deterministic).
  * ``gpu``  — cuGraph SSSP per origin (Spark only, gated by the P00 RAPIDS
               smoke test; auto-falls back to CPU when unavailable).

``all_or_nothing(net, costs, od_by_origin, backend=…)`` returns the per-link
auxiliary flow from loading the full OD onto current shortest paths.
"""

from __future__ import annotations

import numpy as np

from ..network import Network


def all_or_nothing(
    net: Network,
    costs: np.ndarray,
    od_by_origin: dict,
    *,
    backend: str = "cpu",
) -> np.ndarray:
    """Load OD onto shortest paths under ``costs``; return aux link flows.

    ``od_by_origin``: ``{origin_node: [(dest_node, demand), ...]}``.
    """
    if backend == "gpu":
        try:
            from . import gpu

            return gpu.all_or_nothing(net, costs, od_by_origin)
        except Exception as exc:  # noqa: BLE001 — RAPIDS unavailable/unsupported
            import warnings

            warnings.warn(
                f"GPU backend unavailable ({exc!r}); falling back to CPU.",
                RuntimeWarning,
                stacklevel=2,
            )
    from . import cpu

    return cpu.all_or_nothing(net, costs, od_by_origin)


def available_backends() -> list[str]:
    backends = ["cpu"]
    try:
        import cudf  # noqa: F401
        import cugraph  # noqa: F401

        backends.append("gpu")
    except Exception:  # noqa: BLE001
        pass
    return backends


__all__ = ["all_or_nothing", "available_backends", "Network", "np"]
