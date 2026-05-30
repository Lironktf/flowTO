"""Shortest-path backends for the equilibrium AON loading step (P04).

One interface, three implementations:
  * ``cpu``   — heap Dijkstra over the CSR (always available, deterministic).
  * ``scipy`` — vectorized ``csgraph.dijkstra`` (all origins in one C call;
                always available, deterministic, ~30x faster than ``cpu`` on
                the Toronto graph — the recommended CPU backend).
  * ``gpu``   — cuGraph SSSP per origin (Spark only, gated by the P00 RAPIDS
                smoke test; auto-falls back to CPU when unavailable). Note: on
                a city-scale graph this loses to ``scipy`` because cuGraph has
                no multi-source SSSP — kept for very large graphs / analytics.

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
    elif backend == "scipy":
        try:
            from . import scipy_backend

            return scipy_backend.all_or_nothing(net, costs, od_by_origin)
        except Exception as exc:  # noqa: BLE001 — scipy missing/unsupported
            import warnings

            warnings.warn(
                f"scipy backend unavailable ({exc!r}); falling back to CPU.",
                RuntimeWarning,
                stacklevel=2,
            )
    from . import cpu

    return cpu.all_or_nothing(net, costs, od_by_origin)


def available_backends() -> list[str]:
    backends = ["cpu"]
    try:
        import scipy  # noqa: F401

        backends.append("scipy")
    except Exception:  # noqa: BLE001
        pass
    try:
        import cudf  # noqa: F401
        import cugraph  # noqa: F401

        backends.append("gpu")
    except Exception:  # noqa: BLE001
        pass
    return backends


__all__ = ["all_or_nothing", "available_backends", "Network", "np"]
