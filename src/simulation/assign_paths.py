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
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List

import networkx as nx

INF = float("inf")
CLOSED_WEIGHT = 1e12          # effectively-infinite weight for closed edges
PENALTY = 3.0                 # multiplier applied to used edges to find alternates


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
            graph.edges[u, v, k]["load"] = (
                graph.edges[u, v, k].get("load", 0.0) or 0.0) + trips


def k_paths_from_origin(graph, origin, targets, k):
    """Return {target: [path1, path2, ...]} of up to k distinct node paths.

    Uses single-source Dijkstra + edge penalisation. Penalties live on a
    throwaway ``_pen`` attribute layered over ``_eff_w`` so the base weights are
    untouched for the next origin.
    """
    # Working weight = _eff_w * penalty. Start with no penalty.
    for _, _, data in graph.edges(data=True):
        data["_pen"] = data.get("_eff_w", CLOSED_WEIGHT)

    result: Dict[object, List[list]] = defaultdict(list)
    targets = set(targets)
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
        if not progressed:
            break
    return result


def assign_demand_to_paths(graph, od_matrix, k: int = 3, reset: bool = True):
    """Assign every OD pair's trips across its top-k paths. Mutates `graph`.

    After this, each edge has an updated `load`. Call `update_edge_congestion`
    to turn loads into pressure / travel time / risk.
    """
    if reset:
        for _, _, data in graph.edges(data=True):
            data["load"] = 0.0

    _set_eff_weights(graph)

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
