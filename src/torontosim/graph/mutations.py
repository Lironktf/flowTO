"""
Graph mutation utilities for traffic scenarios.

These functions let the simulation engine build "what-if" scenarios on top of
the base Toronto road graph: close roads, throttle capacity (construction),
add new segments, and so on. They operate in place on a
`networkx.MultiDiGraph` and keep the edge_id index consistent.

Only `networkx` is required at runtime.
"""

from __future__ import annotations

from typing import List, Optional

import networkx as nx

from .config import base_time_min, haversine_m
from .routing import (
    build_edge_index,
    get_edge_data,
    get_edge_key,
    make_edge_id,
)

INF = float("inf")


def close_edge(graph: nx.MultiDiGraph, edge_id: str) -> dict:
    """Close a road segment.

    Sets status -> "closed", capacity -> 0, current_time_min -> infinity.
    The pre-close capacity / current_time are stashed so `reopen_edge` can
    restore them exactly.
    """
    data = get_edge_data(graph, edge_id)
    if data.get("status") != "closed":
        data["_capacity_before_close"] = data.get("capacity", 0)
        data["_current_time_before_close"] = data.get("current_time_min")
    data["status"] = "closed"
    data["capacity"] = 0
    data["current_time_min"] = INF
    return data


def reopen_edge(graph: nx.MultiDiGraph, edge_id: str) -> dict:
    """Reopen a previously closed road segment.

    Restores status, capacity, and current_time_min. If no pre-close snapshot
    exists, capacity falls back to the stored `capacity` and current_time_min
    falls back to base_time_min.
    """
    data = get_edge_data(graph, edge_id)
    data["status"] = "open"
    if "_capacity_before_close" in data:
        data["capacity"] = data.pop("_capacity_before_close")
    prev_time = data.pop("_current_time_before_close", None)
    if prev_time is not None and prev_time != INF:
        data["current_time_min"] = prev_time
    else:
        data["current_time_min"] = data.get("base_time_min", INF)
    return data


def change_capacity(graph: nx.MultiDiGraph, edge_id: str, multiplier: float) -> dict:
    """Scale an edge's capacity (e.g. 0.5 for a lane-reducing construction zone).

    Multiplies the current capacity by `multiplier`. Does not touch status or
    travel time — congestion effects are the simulation engine's job.
    """
    data = get_edge_data(graph, edge_id)
    current = data.get("capacity", 0) or 0
    data["capacity"] = current * multiplier
    return data


def add_edge(
    graph: nx.MultiDiGraph,
    from_node,
    to_node,
    road_name: str,
    speed_kmh: float,
    lanes: float,
    capacity: float,
    *,
    road_class: str = "custom",
    one_way: bool = True,
    length_m: Optional[float] = None,
    geometry: Optional[list] = None,
) -> str:
    """Add a new road segment between two existing nodes.

    Length is computed from the node coordinates (haversine) when not given,
    and base/current travel time are derived from length + speed. Returns the
    new edge_id.
    """
    if from_node not in graph:
        raise KeyError(f"from_node {from_node!r} not in graph")
    if to_node not in graph:
        raise KeyError(f"to_node {to_node!r} not in graph")

    if length_m is None:
        a, b = graph.nodes[from_node], graph.nodes[to_node]
        alat = a.get("y", a.get("lat"))
        alon = a.get("x", a.get("lon"))
        blat = b.get("y", b.get("lat"))
        blon = b.get("x", b.get("lon"))
        if None in (alat, alon, blat, blon):
            length_m = 0.0
        else:
            length_m = haversine_m(alat, alon, blat, blon)

    bt = base_time_min(length_m, speed_kmh)

    key = graph.add_edge(from_node, to_node)  # returns the assigned multi-key
    edge_id = make_edge_id(from_node, to_node, key)
    data = graph.edges[from_node, to_node, key]
    data.update(
        {
            "edge_id": edge_id,
            "from_node": from_node,
            "to_node": to_node,
            "road_name": road_name,
            "road_class": road_class,
            "length_m": length_m,
            "one_way": one_way,
            "speed_kmh": speed_kmh,
            "lanes": lanes,
            "capacity": capacity,
            "base_time_min": bt,
            "current_time_min": bt,
            "status": "open",
            "load": 0,
            "pressure": 0,
            "geometry": geometry,
        }
    )

    # Keep the index up to date.
    index = graph.graph.get("_edge_index")
    if index is None:
        index = build_edge_index(graph)
    index[edge_id] = (from_node, to_node, key)

    _refresh_degrees(graph, (from_node, to_node))
    return edge_id


def remove_edge(graph: nx.MultiDiGraph, edge_id: str) -> None:
    """Remove an edge from the graph entirely.

    (Use `close_edge` instead if you want a reversible closure that keeps the
    segment in the data for before/after comparison.)
    """
    u, v, k = get_edge_key(graph, edge_id)
    graph.remove_edge(u, v, k)
    index = graph.graph.get("_edge_index")
    if index is not None:
        index.pop(str(edge_id), None)
    _refresh_degrees(graph, (u, v))


def incident_edge_ids(graph: nx.MultiDiGraph, node_id) -> List[str]:
    """All edge_ids attached to a node (incoming + outgoing), WITHOUT mutating.

    The set of edges a ``close_node`` (blocked intersection) would close. Shared by
    ``close_node`` and the residual closure-GNN path, which expands an intersection
    block into these per-edge closures to build its intervention mask.
    """
    if node_id not in graph:
        raise KeyError(f"node {node_id!r} not in graph")

    ids: List[str] = []
    for u, v, k, data in graph.in_edges(node_id, keys=True, data=True):
        ids.append(data.get("edge_id") or make_edge_id(u, v, k))
    for u, v, k, data in graph.out_edges(node_id, keys=True, data=True):
        ids.append(data.get("edge_id") or make_edge_id(u, v, k))
    return ids


def close_node(graph: nx.MultiDiGraph, node_id) -> List[str]:
    """Close every edge attached to a node (all incoming and outgoing).

    Returns the list of edge_ids that were closed. Useful for simulating a
    fully blocked intersection.
    """
    # Collect first (incident_edge_ids snapshots into a list), because closing
    # mutates edge data while we would otherwise iterate.
    closed: List[str] = []
    for eid in incident_edge_ids(graph, node_id):
        close_edge(graph, eid)
        closed.append(eid)
    return closed


def _refresh_degrees(graph: nx.MultiDiGraph, nodes) -> None:
    """Recompute the cached `degree` attribute for the given nodes."""
    for n in nodes:
        if n in graph:
            graph.nodes[n]["degree"] = graph.degree(n)
