"""CPU shortest-path backend: heap Dijkstra over the CSR (P04).

Deterministic: the priority queue is keyed ``(distance, node)`` so equal-
distance nodes pop in node-id order, and link relaxation keeps the lowest-cost
(then lowest edge-index) predecessor — killing shortest-path-tie nondeterminism
without needing a cost epsilon. ``float64`` distances.
"""

from __future__ import annotations

import heapq

import numpy as np

from ..network import Network


def _dijkstra(net: Network, costs: np.ndarray, origin: int):
    """Single-source shortest paths -> (dist, pred_link) arrays."""
    n = net.n_nodes
    dist = np.full(n, np.inf, dtype=np.float64)
    pred_link = np.full(n, -1, dtype=np.int64)
    dist[origin] = 0.0
    pq = [(0.0, origin)]
    indptr, order, head = net.indptr, net.order, net.head
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for idx in range(indptr[u], indptr[u + 1]):
            link = order[idx]
            c = costs[link]
            if not np.isfinite(c):
                continue
            v = head[link]
            nd = d + c
            # Strict improvement, with a deterministic tie-break on equal
            # distance: prefer the lower edge index as predecessor.
            if nd < dist[v] or (nd == dist[v] and link < pred_link[v]):
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
                pred_link[v] = link
    return dist, pred_link


def all_or_nothing(net: Network, costs: np.ndarray, od_by_origin: dict) -> np.ndarray:
    """Load OD onto shortest paths; return per-link auxiliary flow (float64)."""
    aux = np.zeros(net.n_links, dtype=np.float64)
    tail = net.tail
    for origin in sorted(od_by_origin):
        dests = od_by_origin[origin]
        _dist, pred_link = _dijkstra(net, costs, origin)
        for dest, demand in dests:
            if demand <= 0:
                continue
            v = dest
            # Walk predecessor links back to the origin, loading demand.
            while v != origin:
                link = pred_link[v]
                if link < 0:
                    break  # unreachable
                aux[link] += demand
                v = tail[link]
    return aux
