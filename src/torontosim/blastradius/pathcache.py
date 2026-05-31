"""Baseline path cache + edge→paths reverse index (P05).

Precompute each OD bundle's shortest path at baseline, reusing SSSP trees so
affected-path lookup after a change is O(1): ``edge_to_ods[link]`` gives every
OD whose cached path crosses that link.

GPU support: ``build_path_cache(..., backend="gpu")`` calls ``sssp_all_predecessors``
once to build the cuGraph G and run SSSP for every origin in a single pass, then
traces paths from the predecessor dicts on the CPU side. Falls back to CPU
Dijkstra if cuGraph is unavailable.
"""

from __future__ import annotations

import numpy as np

from ..simulation.backends.cpu import _dijkstra
from ..simulation.network import Network


class PathCache:
    """Per-OD shortest paths (as link lists) + reverse index link -> OD ids."""

    def __init__(self, od, paths, edge_to_ods):
        self.od = od  # list of (origin, dest, demand)
        self.paths = paths  # list[list[int]] aligned to od
        self.edge_to_ods = edge_to_ods  # dict[int, set[int]]

    def affected_ods(self, changed_links) -> set:
        """OD indices whose cached path uses any of ``changed_links``."""
        out: set = set()
        for link in changed_links:
            out |= self.edge_to_ods.get(int(link), set())
        return out


def _trace_path(pred_link, tail, origin, dest) -> list:
    """Reconstruct the link list origin->dest from a predecessor-link array (CPU)."""
    links: list = []
    v = dest
    while v != origin:
        link = int(pred_link[v])
        if link < 0:
            return []  # unreachable
        links.append(link)
        v = int(tail[link])
    links.reverse()
    return links


def _trace_path_from_pred(
    pred_dict: dict,
    lut: dict,
    eff_cost: np.ndarray,
    tail: np.ndarray,
    origin: int,
    dest: int,
) -> list:
    """Reconstruct a link-index path from a {vertex: pred_vertex} dict (GPU output).

    Uses ``lut`` (edge lookup dict) + ``eff_cost`` to select among parallel edges,
    consistent with the tie-break rule used when building the cuGraph G.
    """
    links: list = []
    v = int(dest)
    while v != origin:
        p = int(pred_dict.get(v, -1))
        if p < 0:
            return []
        candidates = lut.get((p, v))
        if not candidates:
            return []
        link = min(candidates, key=lambda li: eff_cost[li])
        links.append(link)
        v = p
    links.reverse()
    return links


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


def _build_path_cache_cpu(net: Network, od, costs: np.ndarray, by_origin: dict):
    """CPU variant: per-origin heap Dijkstra."""
    paths: list = [[] for _ in od]
    edge_to_ods: dict = {}
    for origin in sorted(by_origin):
        _dist, pred_link = _dijkstra(net, costs, origin)
        for idx, dest, _demand in by_origin[origin]:
            path = _trace_path(pred_link, net.tail, origin, dest)
            paths[idx] = path
            for link in path:
                edge_to_ods.setdefault(link, set()).add(idx)
    return paths, edge_to_ods


def _build_path_cache_gpu(net: Network, od, costs: np.ndarray, by_origin: dict):
    """GPU variant: single cuGraph G built once; SSSP per origin reuses it."""
    from ..simulation.backends.gpu import _edge_lookup, _eff_costs, sssp_all_predecessors

    ec = _eff_costs(net, costs)
    lut = _edge_lookup(net)
    pred_trees = sssp_all_predecessors(net, costs, sorted(by_origin))

    paths: list = [[] for _ in od]
    edge_to_ods: dict = {}
    for origin in sorted(by_origin):
        pred = pred_trees.get(int(origin), {})
        for idx, dest, _demand in by_origin[origin]:
            path = _trace_path_from_pred(pred, lut, ec, net.tail, int(origin), int(dest))
            paths[idx] = path
            for link in path:
                edge_to_ods.setdefault(link, set()).add(idx)
    return paths, edge_to_ods


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_path_cache(
    net: Network,
    od,
    costs: np.ndarray,
    *,
    backend: str = "cpu",
) -> PathCache:
    """Build a cache of shortest paths per OD under ``costs``.

    ``backend="gpu"`` uses cuGraph SSSP (requires cudf + cugraph, Spark only);
    falls back to CPU heap Dijkstra if unavailable.
    """
    by_origin: dict = {}
    for idx, (o, d, demand) in enumerate(od):
        by_origin.setdefault(int(o), []).append((idx, int(d), float(demand)))

    if backend == "gpu":
        try:
            paths, edge_to_ods = _build_path_cache_gpu(net, od, costs, by_origin)
        except Exception as exc:  # noqa: BLE001 — RAPIDS unavailable
            import warnings

            warnings.warn(
                f"GPU pathcache unavailable ({exc!r}); falling back to CPU.",
                RuntimeWarning,
                stacklevel=2,
            )
            paths, edge_to_ods = _build_path_cache_cpu(net, od, costs, by_origin)
    else:
        paths, edge_to_ods = _build_path_cache_cpu(net, od, costs, by_origin)

    return PathCache(od, paths, edge_to_ods)


def aon_flow(net: Network, od, paths) -> np.ndarray:
    """Sum OD demand along each cached path -> per-link AON flow."""
    flow = np.zeros(net.n_links, dtype=np.float64)
    for (_o, _d, demand), path in zip(od, paths):
        for link in path:
            flow[link] += demand
    return flow
