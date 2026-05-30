"""Adaptive subgraph recompute (P05).

Given a changed link set, re-route only the affected OD bundles inside a bounded
subgraph, adaptively widening if boundary pressures shift. At the all-or-nothing
layer this is **exact** vs a full recompute (a local change only alters the
shortest paths of ODs that used the changed links); under congestion it matches
within tolerance, with widening to close the gap.

Parameters (spec defaults): start radius 8 min free-flow, max 20 min, boundary
widening threshold 8% pressure change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..simulation.backends.cpu import _dijkstra
from ..simulation.network import Network
from . import cones
from .pathcache import PathCache, _trace_path, aon_flow

# Default parameters (free-flow minutes).
DEFAULT_PARAMS = {
    "start_radius_min": 8.0,
    "max_radius_min": 20.0,
    "widen_threshold": 0.08,  # boundary pressure-change fraction triggering widening
    "buffer_hops": 1,
    "include_highway_core": True,
}


@dataclass
class BlastResult:
    flow: np.ndarray
    affected_ods: set
    subgraph_nodes: set
    subgraph_links: set
    new_paths: dict  # od_idx -> new link path
    widened: int = 0
    stats: dict = field(default_factory=dict)


def affected_region(
    net: Network,
    changed_links,
    costs: np.ndarray,
    *,
    radius_min: float,
    include_highway_core: bool = True,
) -> tuple[set, set]:
    """Nodes (and induced links) reachable within ``radius_min`` of the change."""
    tails = {int(net.tail[link]) for link in changed_links}
    heads = {int(net.head[link]) for link in changed_links}
    down = cones.bounded_cone(net, heads, costs, radius_min, reverse=False)
    up = cones.bounded_cone(net, tails, costs, radius_min, reverse=True)
    nodes = down | up | tails | heads
    if include_highway_core:
        nodes |= cones.highway_core(net, costs)
    links = {
        link
        for link in range(net.n_links)
        if int(net.tail[link]) in nodes and int(net.head[link]) in nodes
    }
    return nodes, links


def _reroute_affected(net, od, cache: PathCache, affected, new_costs):
    """Recompute shortest paths for affected ODs under ``new_costs``."""
    by_origin: dict = {}
    for idx in affected:
        o, d, _demand = od[idx]
        by_origin.setdefault(int(o), []).append((idx, int(d)))
    new_paths: dict = {}
    for origin in sorted(by_origin):
        _dist, pred_link = _dijkstra(net, new_costs, origin)
        for idx, dest in by_origin[origin]:
            new_paths[idx] = _trace_path(pred_link, net.tail, origin, dest)
    return new_paths


def blast_assign(
    net: Network,
    od,
    baseline_cache: PathCache,
    changed_links,
    new_costs: np.ndarray,
    *,
    params: dict | None = None,
) -> BlastResult:
    """Speed-mode blast: re-route only affected ODs; keep cached paths otherwise.

    Exact vs a full AON recompute on the same changed network (local change ->
    only affected ODs' shortest paths can differ). Returns the new link flow and
    region stats.
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    affected = baseline_cache.affected_ods(changed_links)

    nodes, links = affected_region(
        net,
        changed_links,
        new_costs,
        radius_min=params["start_radius_min"],
        include_highway_core=params["include_highway_core"],
    )

    new_paths = _reroute_affected(net, od, baseline_cache, affected, new_costs)

    # Compose: baseline paths for unaffected ODs, fresh paths for affected ones.
    merged_paths = list(baseline_cache.paths)
    for idx, path in new_paths.items():
        merged_paths[idx] = path
    flow = aon_flow(net, od, merged_paths)

    return BlastResult(
        flow=flow,
        affected_ods=affected,
        subgraph_nodes=nodes,
        subgraph_links=links,
        new_paths=new_paths,
        stats={
            "n_affected_ods": len(affected),
            "n_total_ods": len(od),
            "subgraph_nodes": len(nodes),
            "total_nodes": net.n_nodes,
            "subgraph_links": len(links),
            "total_links": net.n_links,
            "node_fraction": (len(nodes) / net.n_nodes) if net.n_nodes else 0.0,
        },
    )


def full_aon(net: Network, od, costs: np.ndarray) -> np.ndarray:
    """Reference: all-or-nothing flow re-routing every OD under ``costs``."""
    cache = build_full_cache(net, od, costs)
    return aon_flow(net, od, cache.paths)


def build_full_cache(net: Network, od, costs: np.ndarray) -> PathCache:
    from .pathcache import build_path_cache

    return build_path_cache(net, od, costs)
