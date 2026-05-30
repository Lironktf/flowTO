"""Bounded upstream/downstream cones for the affected subgraph (P05).

A change at link ``e`` can only be detoured around within a bounded travel-time
radius. We grow a **downstream** cone forward from ``e``'s head (toward likely
destinations) and an **upstream** cone backward from ``e``'s tail (toward likely
origins) with cost-bounded Dijkstra, then union them (+ a buffer) into the
affected node set. Highway/expressway connectors are always included so non-
local detours aren't missed.
"""

from __future__ import annotations

import heapq

import numpy as np

from ..simulation.network import Network


def _reverse_csr(net: Network):
    """CSR of the reversed graph: for incoming links grouped by head node."""
    order = np.argsort(net.head, kind="stable")
    indptr = np.zeros(net.n_nodes + 1, dtype=np.int64)
    counts = np.bincount(net.head, minlength=net.n_nodes)
    indptr[1:] = np.cumsum(counts)
    return indptr, order.astype(np.int64)


def bounded_cone(
    net: Network,
    sources,
    costs: np.ndarray,
    max_cost: float,
    *,
    reverse: bool = False,
) -> set:
    """Nodes within ``max_cost`` of any source (forward, or reverse adjacency)."""
    if reverse:
        indptr, order = _reverse_csr(net)
        neigh = net.tail  # follow links backward: arrive at the tail
    else:
        indptr, order = net.indptr, net.order
        neigh = net.head

    dist = {int(s): 0.0 for s in sources}
    pq = [(0.0, int(s)) for s in sources]
    heapq.heapify(pq)
    visited: set = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for idx in range(indptr[u], indptr[u + 1]):
            link = int(order[idx])
            c = costs[link]
            if not np.isfinite(c):
                continue
            nd = d + c
            if nd > max_cost:
                continue
            v = int(neigh[link])
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return set(dist)


def highway_core(net: Network, costs: np.ndarray) -> set:
    """Endpoints of the high-capacity (expressway) links — always kept.

    Capacity is a good proxy for road class in the link network; the top
    capacity tier is the connector core that carries non-local detours.
    """
    if net.n_links == 0:
        return set()
    cap = net.cap
    finite = cap[np.isfinite(cap) & (cap > 0)]
    if finite.size == 0:
        return set()
    threshold = np.percentile(finite, 90)
    nodes: set = set()
    for link in range(net.n_links):
        if cap[link] >= threshold:
            nodes.add(int(net.tail[link]))
            nodes.add(int(net.head[link]))
    return nodes
