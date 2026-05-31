"""
Assign OD trips onto the graph's best paths.

For each OD pair we find up to K good paths (by current travel time), split the
trips across them by attractiveness (1 / route_time), and add the resulting
load to every edge along each path.

Performance: per origin we run a single-source Dijkstra (one call gives the
shortest path to *all* of that origin's destinations), then get alternates by
penalising the edges already used and re-running. Dijkstra uses a plain edge
attribute ``_eff_w`` so NetworkX can take its fast C path (a Python weight
callable is ~10x slower). ``_eff_w`` also encodes closures (huge weight) so
closed edges are naturally avoided.

GPU support: ``backend="gpu"`` converts the NetworkX graph to the compact
Network format once, then uses cuGraph SSSP (via ``gpu.kpath_sssp``) for all
k-path passes with a NumPy penalty array instead of mutating graph attributes.
Falls back to the NetworkX CPU path if cuGraph is unavailable.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List

import networkx as nx

INF = float("inf")
CLOSED_WEIGHT = 1e12  # effectively-infinite weight for closed edges
PENALTY = 3.0  # multiplier applied to used edges to find alternates


def _set_eff_weights(graph):
    """Refresh the ``_eff_w`` routing weight from current_time_min + status."""
    for _, _, data in graph.edges(data=True):
        if data.get("status") == "closed":
            data["_eff_w"] = CLOSED_WEIGHT
            continue
        ct = data.get("current_time_min")
        if ct is None or (isinstance(ct, float) and math.isinf(ct)):
            data["_eff_w"] = CLOSED_WEIGHT
        else:
            data["_eff_w"] = float(ct)


def _cheapest_edge_key(graph, u, v):
    """Key of the open parallel u->v edge with the smallest current_time_min."""
    ed = graph.get_edge_data(u, v)
    if not ed:
        return None
    best_k, best = None, INF
    for k, d in ed.items():
        if d.get("status") == "closed":
            continue
        ct = d.get("current_time_min", INF)
        try:
            ct = float(ct)
        except (TypeError, ValueError):
            continue
        if ct < best:
            best, best_k = ct, k
    return best_k


def _path_time(graph, path):
    """Real (unpenalised) travel time along a node path, via cheapest edges."""
    total = 0.0
    for u, v in zip(path[:-1], path[1:]):
        k = _cheapest_edge_key(graph, u, v)
        if k is None:
            return INF
        total += float(graph.edges[u, v, k].get("current_time_min", 0.0) or 0.0)
    return total


def _add_load(graph, path, trips):
    """Add `trips` to the cheapest edge of every segment along `path`."""
    for u, v in zip(path[:-1], path[1:]):
        k = _cheapest_edge_key(graph, u, v)
        if k is not None:
            graph.edges[u, v, k]["load"] = (graph.edges[u, v, k].get("load", 0.0) or 0.0) + trips


def k_paths_from_origin(graph, origin, targets, k):
    """Return {target: [path1, path2, ...]} of up to k distinct node paths.

    Uses single-source Dijkstra + edge penalisation. Penalties live on a
    throwaway ``_pen`` attribute layered over ``_eff_w`` so the base weights are
    untouched for the next origin.

    The ``_pen`` layer is initialised once per assignment pass by the caller
    (``assign_demand_to_paths``); each origin only restores the handful of edges
    *it* penalised back to ``_eff_w`` on exit, so the invariant "every edge's
    ``_pen`` equals its ``_eff_w`` when an origin starts" still holds — but
    without an O(edges) sweep per origin (which dominated multi-origin runs).
    """
    result: Dict[object, List[list]] = defaultdict(list)
    targets = set(targets)
    penalized: list = []  # (u, v, kk) edges this origin bumped, to restore on exit
    for _ in range(k):
        try:
            _, paths = nx.single_source_dijkstra(graph, origin, weight="_pen")
        except nx.NodeNotFound:
            break
        progressed = False
        for t in targets:
            p = paths.get(t)
            if not p or len(p) < 2:
                continue
            if any(p == existing for existing in result[t]):
                continue  # identical to a path we already have
            result[t].append(p)
            progressed = True
            # Penalise this path's edges so the next round seeks alternates.
            for u, v in zip(p[:-1], p[1:]):
                kk = _cheapest_edge_key(graph, u, v)
                if kk is not None:
                    graph.edges[u, v, kk]["_pen"] *= PENALTY
                    penalized.append((u, v, kk))
        if not progressed:
            break
    # Restore only the edges we touched so the next origin starts clean.
    for u, v, kk in penalized:
        data = graph.edges[u, v, kk]
        data["_pen"] = data.get("_eff_w", CLOSED_WEIGHT)
    return result


# ---------------------------------------------------------------------------
# GPU k-path assignment
# ---------------------------------------------------------------------------


def _assign_gpu(graph, od_matrix, k: int, reset: bool):
    """GPU k-path assignment using Network + cuGraph (Spark only).

    Converts the NetworkX graph to the compact Network format once, extracts
    routing costs from ``current_time_min``, runs ``kpath_sssp`` per origin
    (cuGraph SSSP with NumPy penalty array), and writes loads back to graph edges.
    """
    from ..simulation.equilibrium import network_from_graph
    from .backends.gpu import kpath_sssp

    if reset:
        for _, _, data in graph.edges(data=True):
            data["load"] = 0.0

    net, node_index, edge_keys = network_from_graph(graph)

    # Build routing cost array from current_time_min (not free-flow t0).
    # edge_keys[i] = (u, v, k) determines the link ordering in net.
    import numpy as np

    costs = np.array(
        [
            (
                float(graph[u][v][ek].get("current_time_min") or INF)
                if graph[u][v][ek].get("status") != "closed"
                else INF
            )
            for u, v, ek in edge_keys
        ],
        dtype=np.float64,
    )

    # Group OD by origin (NetworkX node id -> list of OD dicts).
    by_origin: dict = defaultdict(list)
    for od in od_matrix:
        if od["origin"] in node_index and od["destination"] in node_index:
            by_origin[od["origin"]].append(od)

    for origin_nx, ods in by_origin.items():
        origin_net = node_index[origin_nx]
        targets_nx = [od["destination"] for od in ods if od["destination"] in node_index]
        if not targets_nx:
            continue
        targets_net = [node_index[t] for t in targets_nx]

        paths_by_target = kpath_sssp(net, costs, origin_net, targets_net, k, PENALTY)

        for od in ods:
            dest_nx = od["destination"]
            dest_net = node_index.get(dest_nx)
            if dest_net is None:
                continue
            link_paths = paths_by_target.get(dest_net, [])
            if not link_paths:
                continue

            trips = od.get("trips", 0.0)
            if not trips or trips <= 0:
                continue

            # Time weights from unpenalised routing costs.
            times = [
                sum(costs[li] for li in lpath if math.isfinite(costs[li])) for lpath in link_paths
            ]
            inv = [1.0 / t if t > 0 and math.isfinite(t) else 0.0 for t in times]
            s = sum(inv)
            if s <= 0:
                continue

            for lpath, w in zip(link_paths, inv):
                share = trips * (w / s)
                for li in lpath:
                    u, v, ek = edge_keys[li]
                    if graph.has_edge(u, v, ek):
                        graph[u][v][ek]["load"] = (graph[u][v][ek].get("load", 0.0) or 0.0) + share

    return graph


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assign_demand_to_paths(
    graph,
    od_matrix,
    k: int = 3,
    reset: bool = True,
    backend: str = "cpu",
):
    """Assign every OD pair's trips across its top-k paths. Mutates `graph`.

    After this, each edge has an updated `load`. Call `update_edge_congestion`
    to turn loads into pressure / travel time / risk.

    ``backend="gpu"`` uses cuGraph SSSP via the Network format (Spark only);
    falls back to CPU NetworkX Dijkstra if unavailable.
    """
    if backend == "gpu":
        try:
            return _assign_gpu(graph, od_matrix, k=k, reset=reset)
        except Exception as exc:  # noqa: BLE001 — RAPIDS unavailable
            import warnings

            warnings.warn(
                f"GPU assign unavailable ({exc!r}); falling back to CPU.",
                RuntimeWarning,
                stacklevel=2,
            )

    # CPU path (original NetworkX-based implementation)
    if reset:
        for _, _, data in graph.edges(data=True):
            data["load"] = 0.0

    _set_eff_weights(graph)
    # Initialise the penalty layer once for the whole pass; each origin restores
    # only the edges it touches (see ``k_paths_from_origin``), so we avoid an
    # O(edges) reset per origin.
    for _, _, data in graph.edges(data=True):
        data["_pen"] = data.get("_eff_w", CLOSED_WEIGHT)

    by_origin = defaultdict(list)
    for od in od_matrix:
        by_origin[od["origin"]].append(od)

    for origin, ods in by_origin.items():
        if origin not in graph:
            continue
        targets = {od["destination"] for od in ods if od["destination"] in graph}
        if not targets:
            continue
        paths_by_target = k_paths_from_origin(graph, origin, targets, k)

        for od in ods:
            dest, trips = od["destination"], od["trips"]
            routes = paths_by_target.get(dest)
            if not routes:
                continue  # unreachable (e.g. every path closed) -> trips dropped
            times = [_path_time(graph, p) for p in routes]
            inv = [1.0 / t if t and math.isfinite(t) and t > 0 else 0.0 for t in times]
            s = sum(inv)
            if s <= 0:
                continue
            for p, w in zip(routes, inv):
                _add_load(graph, p, trips * (w / s))

    return graph
