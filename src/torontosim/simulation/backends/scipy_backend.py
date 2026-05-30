"""Vectorized CPU shortest-path backend via SciPy ``csgraph.dijkstra`` (P04).

The CPU heap backend runs one Python-level Dijkstra per origin; for many origins
that Python loop dominates. SciPy's ``dijkstra`` does *all* origins in a single
C call over a CSR matrix, which on the Toronto graph (27k nodes / 73k links) is
~30x faster than the heap backend and ~57x faster than the per-origin cuGraph
SSSP loop — measured on the GB10 (see ``scripts/spark/bench_gpu_sssp.py``).

Determinism: a ``link_index * 1e-9`` epsilon is added to finite costs so equal-
cost ties resolve to the lowest-index predecessor — the same rule the CPU/GPU
backends use, so flows agree across backends. float64 throughout.

Parallel edges (multiple links sharing a (tail, head)) are collapsed to their
minimum effective cost for the CSR; flow is attributed back to the cheapest
parallel link via a cached lookup. The collapsed CSR *structure* (which depends
only on the finite mask, stable across Frank-Wolfe iterations) is cached per
Network; only the per-pair weights are recomputed each call.
"""

from __future__ import annotations

import numpy as np

from ..network import Network

# id(net) -> (finite_key, pair_rows, pair_cols, pair_index, fin_idx, lut)
_CSR_CACHE: dict = {}


def _eff_costs(net: Network, costs: np.ndarray) -> np.ndarray:
    """Finite costs + deterministic tie-break epsilon; inf for zero-cap links."""
    eps = np.arange(net.n_links, dtype=np.float64) * 1e-9
    return np.where(np.isfinite(costs), costs + eps, np.inf)


def _structure(net: Network, eff_cost: np.ndarray):
    """Cached CSR structure for the current finite mask.

    Returns ``(pair_rows, pair_cols, pair_index, fin_idx, lut)`` where unique
    (tail, head) pairs index the CSR, ``pair_index`` maps each finite link to
    its pair, and ``lut`` maps (tail, head) -> [link indices] for attribution.
    """
    finite = np.isfinite(eff_cost)
    fkey = finite.tobytes()
    cached = _CSR_CACHE.get(id(net))
    if cached is not None and cached[0] == fkey:
        return cached[1:]

    fin_idx = np.nonzero(finite)[0]
    tails = net.tail[fin_idx].astype(np.int64)
    heads = net.head[fin_idx].astype(np.int64)
    pairs = tails * net.n_nodes + heads
    uniq, pair_index = np.unique(pairs, return_inverse=True)
    pair_index = pair_index.astype(np.int64).ravel()
    pair_rows = (uniq // net.n_nodes).astype(np.int32)
    pair_cols = (uniq % net.n_nodes).astype(np.int32)

    lut: dict = {}
    for li in fin_idx.tolist():
        lut.setdefault((int(net.tail[li]), int(net.head[li])), []).append(li)

    struct = (pair_rows, pair_cols, pair_index, fin_idx, lut)
    _CSR_CACHE[id(net)] = (fkey, *struct)
    return struct


def all_or_nothing(net: Network, costs: np.ndarray, od_by_origin: dict) -> np.ndarray:
    """Load OD onto shortest paths; return per-link auxiliary flow (float64).

    One ``scipy.sparse.csgraph.dijkstra`` call computes the shortest-path tree
    for every origin at once; paths are then traced from the predecessor matrix.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra

    eff = _eff_costs(net, costs)
    pair_rows, pair_cols, pair_index, fin_idx, lut = _structure(net, eff)

    # Collapse parallel edges: minimum effective cost per unique (tail, head).
    n_pairs = pair_rows.shape[0]
    pair_min = np.full(n_pairs, np.inf, dtype=np.float64)
    np.minimum.at(pair_min, pair_index, eff[fin_idx])

    csr = csr_matrix((pair_min, (pair_rows, pair_cols)), shape=(net.n_nodes, net.n_nodes))

    origins = sorted(od_by_origin)
    if not origins:
        return np.zeros(net.n_links, dtype=np.float64)

    _dist, pred = dijkstra(csr, directed=True, indices=origins, return_predecessors=True)
    oidx = {o: i for i, o in enumerate(origins)}

    aux = np.zeros(net.n_links, dtype=np.float64)
    for origin in origins:
        pr = pred[oidx[origin]]
        for dest, demand in od_by_origin[origin]:
            if demand <= 0:
                continue
            v = int(dest)
            # Walk predecessors back to origin (scipy uses -9999 for no-path).
            while v != origin:
                p = int(pr[v])
                if p < 0:
                    break  # unreachable
                candidates = lut.get((p, v))
                if not candidates:
                    break
                link = min(candidates, key=lambda li: eff[li])
                aux[link] += demand
                v = p
    return aux
