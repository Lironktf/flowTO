"""
Routing and helper utilities for the Toronto road graph.

This module deliberately depends only on `networkx` (plus the standard
library) so the simulation engine can import and use it without needing
OSMnx installed. Building the graph from OpenStreetMap lives in
`build_graph.py`; everything here operates on an already-built graph.

The graph is a `networkx.MultiDiGraph` where:
  * each node carries: x (lon), y (lat), and optionally name + degree
  * each edge carries the simulation fields described in the README, and a
    stable `edge_id` attribute.

Edges are looked up by `edge_id`. We keep a lazily-built index on the graph
object (`graph.graph["_edge_index"]`) mapping edge_id -> (u, v, key).
"""

from __future__ import annotations

import json
import math
from typing import Dict, Optional, Tuple

import networkx as nx

from .config import haversine_m

EdgeKey = Tuple[object, object, int]


# ---------------------------------------------------------------------------
# Edge-id index
# ---------------------------------------------------------------------------


def build_edge_index(graph: nx.MultiDiGraph) -> Dict[str, EdgeKey]:
    """(Re)build and cache the edge_id -> (u, v, key) lookup on the graph.

    Call this after loading a graph from GraphML/pickle, or whenever you are
    unsure the index is fresh. Mutation helpers keep it up to date.
    """
    index: Dict[str, EdgeKey] = {}
    for u, v, k, data in graph.edges(keys=True, data=True):
        eid = data.get("edge_id")
        if eid is None:
            eid = make_edge_id(u, v, k)
            data["edge_id"] = eid
        index[str(eid)] = (u, v, k)
    graph.graph["_edge_index"] = index
    return index


def make_edge_id(u, v, k) -> str:
    """Deterministic, human-readable edge id."""
    return f"{u}-{v}-{k}"


def _index(graph: nx.MultiDiGraph) -> Dict[str, EdgeKey]:
    index = graph.graph.get("_edge_index")
    if index is None:
        index = build_edge_index(graph)
    return index


def get_edge_key(graph: nx.MultiDiGraph, edge_id: str) -> EdgeKey:
    """Resolve an edge_id to the (u, v, key) tuple networkx uses."""
    index = _index(graph)
    key = index.get(str(edge_id))
    if key is None:
        # Index may be stale (e.g. edge added without going through helpers).
        index = build_edge_index(graph)
        key = index.get(str(edge_id))
    if key is None:
        raise KeyError(f"edge_id {edge_id!r} not found in graph")
    return key


def get_edge_data(graph: nx.MultiDiGraph, edge_id: str) -> dict:
    """Return the mutable attribute dict for an edge_id."""
    u, v, k = get_edge_key(graph, edge_id)
    return graph.edges[u, v, k]


# ---------------------------------------------------------------------------
# Nearest node / edge (pure-python, haversine based)
# ---------------------------------------------------------------------------


def _node_lat(data: dict) -> Optional[float]:
    if "y" in data:
        return float(data["y"])
    if "lat" in data:
        return float(data["lat"])
    return None


def _node_lon(data: dict) -> Optional[float]:
    if "x" in data:
        return float(data["x"])
    if "lon" in data:
        return float(data["lon"])
    return None


def get_nearest_node(graph: nx.MultiDiGraph, lat: float, lon: float):
    """Return the node id closest to (lat, lon) by great-circle distance."""
    best_node = None
    best_dist = math.inf
    for node, data in graph.nodes(data=True):
        nlat, nlon = _node_lat(data), _node_lon(data)
        if nlat is None or nlon is None:
            continue
        d = haversine_m(lat, lon, nlat, nlon)
        if d < best_dist:
            best_dist = d
            best_node = node
    if best_node is None:
        raise ValueError("graph has no nodes with coordinates")
    return best_node


def _point_to_segment_m(plat, plon, alat, alon, blat, blon) -> float:
    """Approximate distance (m) from point P to segment A-B.

    Uses a local equirectangular projection around P, which is plenty accurate
    at city scale and avoids pulling in shapely.
    """
    # metres-per-degree at this latitude
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(plat))

    ax = (alon - plon) * m_per_deg_lon
    ay = (alat - plat) * m_per_deg_lat
    bx = (blon - plon) * m_per_deg_lon
    by = (blat - plat) * m_per_deg_lat
    # P is the origin (0,0). Project origin onto segment AB.
    abx, aby = bx - ax, by - ay
    seg_len2 = abx * abx + aby * aby
    if seg_len2 == 0:
        return math.hypot(ax, ay)
    t = -(ax * abx + ay * aby) / seg_len2
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * abx, ay + t * aby
    return math.hypot(cx, cy)


def get_nearest_edge(graph: nx.MultiDiGraph, lat: float, lon: float) -> str:
    """Return the edge_id whose geometry passes closest to (lat, lon)."""
    best_eid = None
    best_dist = math.inf
    for u, v, k, data in graph.edges(keys=True, data=True):
        geom = data.get("geometry")
        dist = math.inf
        if geom and isinstance(geom, list) and len(geom) >= 2:
            # geometry stored as [[lat, lon], ...]
            for i in range(len(geom) - 1):
                alat, alon = geom[i][0], geom[i][1]
                blat, blon = geom[i + 1][0], geom[i + 1][1]
                dist = min(dist, _point_to_segment_m(lat, lon, alat, alon, blat, blon))
        else:
            # Fall back to the straight line between the two endpoints.
            ud, vd = graph.nodes[u], graph.nodes[v]
            ulat, ulon = _node_lat(ud), _node_lon(ud)
            vlat, vlon = _node_lat(vd), _node_lon(vd)
            if None in (ulat, ulon, vlat, vlon):
                continue
            dist = _point_to_segment_m(lat, lon, ulat, ulon, vlat, vlon)
        if dist < best_dist:
            best_dist = dist
            best_eid = data.get("edge_id") or make_edge_id(u, v, k)
    if best_eid is None:
        raise ValueError("graph has no edges with usable geometry")
    return str(best_eid)


# ---------------------------------------------------------------------------
# Shortest path
# ---------------------------------------------------------------------------


def _weight_func(weight: str):
    """Build a networkx weight callable that skips closed/impassable edges.

    Returning None for an edge tells networkx to ignore it, so closed edges
    (status == "closed" or an infinite weight) are routed around rather than
    producing an infinite-cost path.

    On a MultiDiGraph, networkx hands a *callable* weight the inner
    ``{key: attrdict}`` dict for all parallel u->v edges, not a single edge's
    attributes. We detect that and return the minimum over the open parallels;
    on a plain digraph `data` is the attribute dict directly.
    """

    def _one(attr):
        if attr.get("status") == "closed":
            return None
        val = attr.get(weight)
        if val is None:
            return None
        try:
            val = float(val)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(val):
            return None
        return val

    def w(u, v, data):
        # Multigraph: values are per-key attribute dicts. Digraph: scalars.
        if data and all(isinstance(val, dict) for val in data.values()):
            costs = [c for c in (_one(a) for a in data.values()) if c is not None]
            return min(costs) if costs else None
        return _one(data)

    return w


def find_shortest_path(
    graph: nx.MultiDiGraph,
    origin_node,
    destination_node,
    weight: str = "current_time_min",
) -> dict:
    """Shortest path between two nodes.

    Returns a dict:
      {
        "found": bool,
        "nodes": [node_id, ...],
        "edges": [edge_id, ...],
        "total_cost": float,            # in the units of `weight`
        "total_distance_m": float,
        "total_time_min": float,
      }

    Closed edges (status == "closed") are excluded from routing.
    """
    result = {
        "found": False,
        "nodes": [],
        "edges": [],
        "total_cost": math.inf,
        "total_distance_m": 0.0,
        "total_time_min": 0.0,
    }

    try:
        nodes = nx.shortest_path(graph, origin_node, destination_node, weight=_weight_func(weight))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return result

    result["found"] = True
    result["nodes"] = nodes

    total_cost = 0.0
    total_dist = 0.0
    total_time = 0.0
    for u, v in zip(nodes[:-1], nodes[1:]):
        # Multiple parallel edges may exist; pick the cheapest open one by weight.
        best = _cheapest_edge(graph, u, v, weight)
        if best is None:
            # Should not happen for a returned path, but stay defensive.
            continue
        k, data = best
        result["edges"].append(data.get("edge_id") or make_edge_id(u, v, k))
        total_cost += float(data.get(weight, 0.0) or 0.0)
        total_dist += float(data.get("length_m", 0.0) or 0.0)
        total_time += float(data.get("current_time_min", 0.0) or 0.0)

    result["total_cost"] = total_cost
    result["total_distance_m"] = total_dist
    result["total_time_min"] = total_time
    return result


def _cheapest_edge(graph: nx.MultiDiGraph, u, v, weight: str):
    """Among parallel u->v edges, return (key, data) of the cheapest open one."""
    best = None
    best_w = math.inf
    edge_dict = graph.get_edge_data(u, v)
    if not edge_dict:
        return None
    for k, data in edge_dict.items():
        if data.get("status") == "closed":
            continue
        try:
            w = float(data.get(weight))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(w):
            continue
        if w < best_w:
            best_w = w
            best = (k, data)
    if best is None:
        # All parallel edges closed; return any so callers don't crash.
        for k, data in edge_dict.items():
            return (k, data)
    return best


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summarize_graph(graph: nx.MultiDiGraph) -> dict:
    """Return (and print) a small summary of the graph's state."""
    num_nodes = graph.number_of_nodes()
    num_edges = graph.number_of_edges()

    open_edges = closed_edges = 0
    total_length_m = 0.0
    classes: Dict[str, int] = {}
    for _, _, data in graph.edges(data=True):
        if data.get("status") == "closed":
            closed_edges += 1
        else:
            open_edges += 1
        total_length_m += float(data.get("length_m", 0.0) or 0.0)
        rc = data.get("road_class", "unknown")
        classes[rc] = classes.get(rc, 0) + 1

    summary = {
        "nodes": num_nodes,
        "edges": num_edges,
        "open_edges": open_edges,
        "closed_edges": closed_edges,
        "total_length_km": round(total_length_m / 1000.0, 2),
        "road_classes": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
    }

    print("=== Toronto road graph summary ===")
    print(f"  nodes:            {summary['nodes']:,}")
    print(f"  edges:            {summary['edges']:,}")
    print(f"  open / closed:    {summary['open_edges']:,} / {summary['closed_edges']:,}")
    print(f"  total road length: {summary['total_length_km']:,} km")
    print("  edges by class:")
    for rc, n in summary["road_classes"].items():
        print(f"      {rc:<14} {n:,}")
    return summary


# ---------------------------------------------------------------------------
# JSON import / export
# ---------------------------------------------------------------------------


def export_graph_json(graph: nx.MultiDiGraph, path: Optional[str] = None) -> dict:
    """Serialise the graph into the clean simulation JSON format.

    If `path` is given, also write it to disk. Returns the dict either way.
    """
    nodes_out = []
    for node, data in graph.nodes(data=True):
        nodes_out.append(
            {
                "id": node,
                "lat": _node_lat(data),
                "lon": _node_lon(data),
                "name": data.get("name"),
                "degree": data.get("degree", graph.degree(node)),
            }
        )

    edges_out = []
    for u, v, k, data in graph.edges(keys=True, data=True):
        edges_out.append(
            {
                "id": data.get("edge_id") or make_edge_id(u, v, k),
                "from": u,
                "to": v,
                "road_name": data.get("road_name"),
                "road_class": data.get("road_class"),
                "length_m": data.get("length_m"),
                "one_way": data.get("one_way"),
                "speed_kmh": data.get("speed_kmh"),
                "lanes": data.get("lanes"),
                "capacity": data.get("capacity"),
                "base_time_min": data.get("base_time_min"),
                "current_time_min": _json_num(data.get("current_time_min")),
                "status": data.get("status", "open"),
                "load": data.get("load", 0),
                "pressure": data.get("pressure", 0),
                "geometry": data.get("geometry"),
            }
        )

    out = {"nodes": nodes_out, "edges": edges_out}
    if path is not None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh)
    return out


def _json_num(value):
    """JSON has no infinity; represent it as the string 'Infinity'."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    if math.isinf(f):
        return "Infinity"
    return f


def import_graph_json(path: str, heal: bool = True) -> nx.MultiDiGraph:
    """Rebuild a MultiDiGraph from the clean simulation JSON format.

    ``heal`` (default on) repairs inconsistent one-way tagging on two-way
    arterials (see ``graph.repair.heal_oneway_arterials``) so a single-segment
    closure can't disconnect a node that is two-way in reality. Pass
    ``heal=False`` to load the raw graph exactly as stored.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    graph = nx.MultiDiGraph()
    for n in data.get("nodes", []):
        graph.add_node(
            n["id"],
            x=n.get("lon"),
            y=n.get("lat"),
            lon=n.get("lon"),
            lat=n.get("lat"),
            name=n.get("name"),
            degree=n.get("degree"),
        )

    for e in data.get("edges", []):
        ct = e.get("current_time_min")
        if ct == "Infinity":
            ct = float("inf")
        graph.add_edge(
            e["from"],
            e["to"],
            edge_id=e["id"],
            road_name=e.get("road_name"),
            road_class=e.get("road_class"),
            length_m=e.get("length_m"),
            one_way=e.get("one_way"),
            speed_kmh=e.get("speed_kmh"),
            lanes=e.get("lanes"),
            capacity=e.get("capacity"),
            base_time_min=e.get("base_time_min"),
            current_time_min=ct,
            status=e.get("status", "open"),
            load=e.get("load", 0),
            pressure=e.get("pressure", 0),
            geometry=e.get("geometry"),
        )

    build_edge_index(graph)
    if heal:
        from .repair import heal_oneway_arterials

        heal_oneway_arterials(graph)  # rebuilds the edge index
    return graph
