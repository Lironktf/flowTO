"""Bounded upstream/downstream cones for the affected subgraph (P05).

A change at link ``e`` can only be detoured around within a bounded travel-time
radius. We grow a **downstream** cone forward from ``e``'s head (toward likely
destinations) and an **upstream** cone backward from ``e``'s tail (toward likely
origins) with cost-bounded Dijkstra, then union them (+ a buffer) into the
affected node set. Highway/expressway connectors are always included so non-
local detours aren't missed.

GPU variant: cuGraph SSSP with a virtual super-source so any number of sources
costs a single GPU kernel launch, regardless of |sources|.
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


def _bounded_cone_cpu(
    net: Network,
    sources,
    costs: np.ndarray,
    max_cost: float,
    *,
    reverse: bool = False,
) -> set:
    """CPU: cost-bounded Dijkstra from ``sources``."""
    if reverse:
        indptr, order = _reverse_csr(net)
        neigh = net.tail
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


def _bounded_cone_gpu(
    net: Network,
    sources,
    costs: np.ndarray,
    max_cost: float,
    *,
    reverse: bool = False,
) -> set:
    """GPU: cuGraph SSSP with a virtual super-source + distance filter.

    A virtual node at index ``net.n_nodes`` is connected to each real source
    with a 0-cost edge, so one SSSP call from the super-source gives the
    minimum distance from *any* source to every reachable node.  The result is
    then filtered by ``<= max_cost``.

    For ``reverse=True`` the edge list is built with tail/head swapped, which
    is equivalent to running SSSP on the transposed graph.
    """
    import cudf
    import cugraph

    sources = [int(s) for s in sources]
    if not sources:
        return set()

    finite = np.isfinite(costs)
    if reverse:
        real_src = net.head[finite].astype(np.int32)
        real_dst = net.tail[finite].astype(np.int32)
    else:
        real_src = net.tail[finite].astype(np.int32)
        real_dst = net.head[finite].astype(np.int32)
    w_arr = costs[finite].astype(np.float64)

    # Virtual super-source edges: super_src -> each real source with weight 0.
    super_src = int(net.n_nodes)
    v_src = np.full(len(sources), super_src, dtype=np.int32)
    v_dst = np.array(sources, dtype=np.int32)
    v_w = np.zeros(len(sources), dtype=np.float64)

    edge_df = cudf.DataFrame(
        {
            "src": np.concatenate([real_src, v_src]),
            "dst": np.concatenate([real_dst, v_dst]),
            "weight": np.concatenate([w_arr, v_w]),
        }
    )
    G = cugraph.Graph(directed=True)
    G.from_cudf_edgelist(edge_df, source="src", destination="dst", edge_attr="weight")

    sssp_df = cugraph.sssp(G, source=super_src)

    verts = sssp_df["vertex"].to_arrow().to_pylist()
    dists = sssp_df["distance"].to_arrow().to_pylist()

    result: set = set()
    for v, d in zip(verts, dists):
        if int(v) == super_src:
            continue
        if d is not None and d <= max_cost:
            result.add(int(v))
    return result


def bounded_cone(
    net: Network,
    sources,
    costs: np.ndarray,
    max_cost: float,
    *,
    reverse: bool = False,
    backend: str = "cpu",
) -> set:
    """Nodes within ``max_cost`` of any source (forward, or reverse adjacency).

    ``backend="gpu"`` uses cuGraph with a virtual super-source (one SSSP call
    for all sources); falls back to CPU heap Dijkstra if unavailable.
    """
    if backend == "gpu":
        try:
            return _bounded_cone_gpu(net, sources, costs, max_cost, reverse=reverse)
        except Exception as exc:  # noqa: BLE001
            import warnings

            warnings.warn(
                f"GPU cone unavailable ({exc!r}); falling back to CPU.",
                RuntimeWarning,
                stacklevel=2,
            )
    return _bounded_cone_cpu(net, sources, costs, max_cost, reverse=reverse)


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
