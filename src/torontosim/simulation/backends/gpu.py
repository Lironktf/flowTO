"""GPU shortest-path backend via cuGraph SSSP (P04, Spark only).

cuGraph has no native multi-source skim, so we loop ``cugraph.sssp`` per origin
(each call is GPU-parallel over targets), reconstruct predecessor trees, and
aggregate OD onto links. Gated by the P00 RAPIDS smoke test; the dispatcher in
``backends/__init__`` auto-falls back to CPU if import/execution fails.

Determinism: a tiny ``edge_index * 1e-9`` epsilon is added to link costs so
equal-cost shortest paths resolve to a unique (lowest-index) predecessor, then
ordered Python-side reductions accumulate flows (no atomics). float64 weights.
"""

from __future__ import annotations

import numpy as np

from ..network import Network

# Resolved per (tail, head) -> ordered list of link indices, built once.
_EDGE_LOOKUP_CACHE: dict[int, dict] = {}


def _edge_lookup(net: Network) -> dict:
    key = id(net)
    cached = _EDGE_LOOKUP_CACHE.get(key)
    if cached is None:
        lut: dict = {}
        for link in range(net.n_links):
            lut.setdefault((int(net.tail[link]), int(net.head[link])), []).append(link)
        _EDGE_LOOKUP_CACHE[key] = lut
        cached = lut
    return cached


def all_or_nothing(net: Network, costs: np.ndarray, od_by_origin: dict) -> np.ndarray:
    """cuGraph AON loading. Requires cudf+cugraph (Spark)."""
    import cudf
    import cugraph

    lut = _edge_lookup(net)
    # Deterministic tie-break epsilon on costs (links with cap<=0 stay inf).
    eps = np.arange(net.n_links, dtype=np.float64) * 1e-9
    eff_cost = np.where(np.isfinite(costs), costs + eps, np.inf)

    # Build the edge list once per call (costs change each FW iteration).
    finite = np.isfinite(eff_cost)
    edge_df = cudf.DataFrame(
        {
            "src": net.tail[finite].astype("int32"),
            "dst": net.head[finite].astype("int32"),
            "weight": eff_cost[finite].astype("float64"),
        }
    )
    G = cugraph.Graph(directed=True)
    G.from_cudf_edgelist(edge_df, source="src", destination="dst", edge_attr="weight")

    aux = np.zeros(net.n_links, dtype=np.float64)
    for origin in sorted(od_by_origin):
        sssp = cugraph.sssp(G, source=int(origin))
        sdf = sssp.set_index("vertex").to_pandas()
        pred = sdf["predecessor"].to_dict()
        for dest, demand in od_by_origin[origin]:
            if demand <= 0:
                continue
            v = int(dest)
            while v != origin:
                p = int(pred.get(v, -1))
                if p < 0:
                    break  # unreachable
                # Cheapest link p->v (tie-broken by lowest index via eps).
                candidates = lut.get((p, v))
                if not candidates:
                    break
                link = min(candidates, key=lambda li: eff_cost[li])
                aux[link] += demand
                v = p
    return aux
