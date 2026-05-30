"""GPU shortest-path backend via cuGraph SSSP (P04, Spark only).

Improvements over v1:
- Topology cache: ``net.cap > 0`` and ``np.isfinite(costs)`` define which edges
  are in the graph. For a given Network instance (fixed topology) the finite mask
  is stable across Frank-Wolfe iterations because only weights change. Caching
  int32 src/dst arrays avoids rebuilding them on every iteration.
- Arrow transfer: predecessor trees pulled GPU→CPU via PyArrow — faster than
  ``.to_pandas().to_dict()`` for large vertex sets (avoids pandas overhead).
- Public SSSP API: ``sssp_predecessors``, ``sssp_all_predecessors``, and
  ``kpath_sssp`` let pathcache, blast-radius, and the k-path engine reuse GPU
  SSSP without duplicating build/dispatch logic.

Determinism: a tiny ``link_index * 1e-9`` epsilon is added to finite link costs
so equal-cost ties resolve to the lowest-index predecessor — matching the CPU
backend. float64 weights throughout.
"""

from __future__ import annotations

import numpy as np

from ..network import Network

# ---------------------------------------------------------------------------
# Topology cache
# ---------------------------------------------------------------------------
# For a given Network instance the finite mask (which edges enter the graph) is
# determined by ``np.isfinite(eff_cost)`` and changes only when edges transition
# between finite and infinite cost (e.g. a link closure). We cache the int32
# src/dst arrays under a (net_id, finite_mask_bytes) key so the cheap slicing
# and astype() calls are skipped on cache hits.
# ---------------------------------------------------------------------------
_TOPO_CACHE: dict = {}  # net_id -> (finite_key: bytes, src_i32, dst_i32)

# Per-net edge lookup: (tail, head) -> sorted list of link indices.
_EDGE_LOOKUP_CACHE: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _eff_costs(net: Network, costs: np.ndarray) -> np.ndarray:
    """Finite costs + deterministic tie-break epsilon; inf for zero-cap links."""
    eps = np.arange(net.n_links, dtype=np.float64) * 1e-9
    return np.where(np.isfinite(costs), costs + eps, np.inf)


def _build_graph(net: Network, eff_cost: np.ndarray):
    """Build a cuGraph directed weighted graph, reusing cached topology arrays."""
    import cudf
    import cugraph

    finite = np.isfinite(eff_cost)
    fkey = finite.tobytes()
    net_id = id(net)
    cached = _TOPO_CACHE.get(net_id)
    if cached is not None and cached[0] == fkey:
        src_i32, dst_i32 = cached[1], cached[2]
    else:
        src_i32 = net.tail[finite].astype(np.int32)
        dst_i32 = net.head[finite].astype(np.int32)
        _TOPO_CACHE[net_id] = (fkey, src_i32, dst_i32)

    edge_df = cudf.DataFrame(
        {
            "src": src_i32,
            "dst": dst_i32,
            "weight": eff_cost[finite].astype(np.float64),
        }
    )
    G = cugraph.Graph(directed=True)
    G.from_cudf_edgelist(edge_df, source="src", destination="dst", edge_attr="weight")
    return G


def _pred_dict(sssp_df) -> dict:
    """Convert a cuGraph SSSP result to {vertex: predecessor} via Arrow (fast).

    Predecessors are -1 for the source node and unreachable nodes — callers
    guard against ``p < 0``, so the sentinel is preserved as a Python int.
    """
    arrow = sssp_df[["vertex", "predecessor"]].to_arrow()
    return {
        int(v): int(p)
        for v, p in zip(
            arrow.column("vertex").to_pylist(),
            arrow.column("predecessor").to_pylist(),
        )
    }


def _edge_lookup(net: Network) -> dict:
    """Per-net (tail, head) -> [link_indices] lookup; built once and cached."""
    net_id = id(net)
    cached = _EDGE_LOOKUP_CACHE.get(net_id)
    if cached is None:
        lut: dict = {}
        for link in range(net.n_links):
            lut.setdefault((int(net.tail[link]), int(net.head[link])), []).append(link)
        _EDGE_LOOKUP_CACHE[net_id] = lut
        cached = lut
    return cached


def _trace_path(
    pred: dict,
    lut: dict,
    eff_cost: np.ndarray,
    tail: np.ndarray,
    origin: int,
    dest: int,
) -> list:
    """Reconstruct a link-index path origin→dest from a {vertex: pred_vertex} dict.

    Uses ``lut`` (edge lookup) + ``eff_cost`` to resolve parallel edges to the
    minimum-cost one — matching the tie-break rule used when building G.
    """
    links: list = []
    v = int(dest)
    while v != origin:
        p = int(pred.get(v, -1))
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
# Public SSSP API
# ---------------------------------------------------------------------------


def sssp_predecessors(net: Network, costs: np.ndarray, origin: int) -> dict:
    """Run cuGraph SSSP from ``origin``; return {vertex: predecessor} dict.

    Uses Arrow for the GPU→CPU transfer. Topology arrays are cached across
    calls with the same finite mask.
    """
    import cugraph

    ec = _eff_costs(net, costs)
    G = _build_graph(net, ec)
    return _pred_dict(cugraph.sssp(G, source=int(origin)))


def sssp_all_predecessors(
    net: Network,
    costs: np.ndarray,
    origins,
) -> dict:
    """GPU SSSP from each origin; return {origin_int: pred_dict}.

    Builds the cuGraph object once and reuses it for every origin — the
    topology and weights are shared, only the source changes.
    """
    import cugraph

    ec = _eff_costs(net, costs)
    G = _build_graph(net, ec)
    result: dict = {}
    for origin in origins:
        o = int(origin)
        result[o] = _pred_dict(cugraph.sssp(G, source=o))
    return result


def kpath_sssp(
    net: Network,
    costs: np.ndarray,
    origin: int,
    targets,
    k: int,
    penalty: float,
) -> dict:
    """GPU k-path finder: return {target_int: [link_path, ...]} for ``origin``.

    Runs up to ``k`` cuGraph SSSP passes with a per-link NumPy penalty array.
    After each pass the penalty for used edges is multiplied by ``penalty`` so
    subsequent passes seek diverse alternatives. The cuGraph G is rebuilt each
    pass (costs change via the penalty), but the topology cache means the
    src/dst arrays are reused while the finite mask stays the same.
    """
    import cugraph

    lut = _edge_lookup(net)
    targets = [int(t) for t in targets]
    pen = np.ones(net.n_links, dtype=np.float64)
    result: dict = {t: [] for t in targets}

    for _ in range(k):
        penalized = np.where(np.isfinite(costs), costs * pen, np.inf)
        ec = _eff_costs(net, penalized)
        G = _build_graph(net, ec)
        pred = _pred_dict(cugraph.sssp(G, source=int(origin)))

        progressed = False
        for t in targets:
            path = _trace_path(pred, lut, ec, net.tail, int(origin), t)
            if not path:
                continue
            if any(path == existing for existing in result[t]):
                continue
            result[t].append(path)
            progressed = True
            for link in path:
                pen[link] *= penalty

        if not progressed:
            break

    return result


# ---------------------------------------------------------------------------
# AON loading (equilibrium engine)
# ---------------------------------------------------------------------------


def all_or_nothing(net: Network, costs: np.ndarray, od_by_origin: dict) -> np.ndarray:
    """cuGraph AON loading. Requires cudf + cugraph (Spark only)."""
    import cugraph

    lut = _edge_lookup(net)
    ec = _eff_costs(net, costs)
    G = _build_graph(net, ec)

    aux = np.zeros(net.n_links, dtype=np.float64)
    for origin in sorted(od_by_origin):
        pred = _pred_dict(cugraph.sssp(G, source=int(origin)))
        for dest, demand in od_by_origin[origin]:
            if demand <= 0:
                continue
            path = _trace_path(pred, lut, ec, net.tail, int(origin), int(dest))
            for link in path:
                aux[link] += demand
    return aux
