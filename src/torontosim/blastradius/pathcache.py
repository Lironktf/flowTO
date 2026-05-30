"""Baseline path cache + edge→paths reverse index (P05).

Precompute each OD bundle's shortest path at baseline (reusing the CPU backend's
SSSP trees) so affected-path lookup after a change is O(1): ``edge_to_ods[link]``
gives every OD whose cached path crosses that link.
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
    """Reconstruct the link list origin->dest from a predecessor-link array."""
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


def build_path_cache(net: Network, od, costs: np.ndarray) -> PathCache:
    """Build a cache of shortest paths per OD under ``costs``."""
    by_origin: dict = {}
    for idx, (o, d, demand) in enumerate(od):
        by_origin.setdefault(int(o), []).append((idx, int(d), float(demand)))

    paths: list = [[] for _ in od]
    edge_to_ods: dict = {}
    for origin in sorted(by_origin):
        _dist, pred_link = _dijkstra(net, costs, origin)
        for idx, dest, _demand in by_origin[origin]:
            path = _trace_path(pred_link, net.tail, origin, dest)
            paths[idx] = path
            for link in path:
                edge_to_ods.setdefault(link, set()).add(idx)
    return PathCache(od, paths, edge_to_ods)


def aon_flow(net: Network, od, paths) -> np.ndarray:
    """Sum OD demand along each cached path -> per-link AON flow."""
    flow = np.zeros(net.n_links, dtype=np.float64)
    for (_o, _d, demand), path in zip(od, paths):
        for link in path:
            flow[link] += demand
    return flow
