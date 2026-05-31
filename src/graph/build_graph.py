"""
Build the Toronto directed road graph from OpenStreetMap via OSMnx.

Run as a script to (re)download the graph, enrich every edge with the fields
the simulation engine needs, and write out:
  * data/graph/toronto_drive_graph.graphml  (NetworkX-reloadable)
  * data/graph/toronto_drive_graph.json     (clean simulation JSON)

    python -m src.graph.build_graph                  # default downtown area
    python -m src.graph.build_graph --place "Toronto, Ontario, Canada"
    python -m src.graph.build_graph --center 43.65 -79.39 --radius 8000

OSMnx is only needed for this build step. The mutation/routing modules work
on the produced graph without it.
"""

from __future__ import annotations

import argparse
import os
from typing import Optional, Tuple

import networkx as nx

from .config import (
    DEFAULT_CENTER,
    DEFAULT_LANES,
    DEFAULT_PLACE,
    DEFAULT_RADIUS_M,
    DEFAULT_SPEED_KMH,
    VEHICLES_PER_HOUR_PER_LANE,
    base_time_min,
    first_value,
    lookup,
    normalise_road_class,
    to_float,
)
from .routing import build_edge_index, export_graph_json, make_edge_id

# Where the deliverables go (repo-root/data/graph).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
DATA_DIR = os.path.join(_REPO_ROOT, "data", "graph")
GRAPHML_PATH = os.path.join(DATA_DIR, "toronto_drive_graph.graphml")
JSON_PATH = os.path.join(DATA_DIR, "toronto_drive_graph.json")


def download_graph(
    place: Optional[str] = None,
    center: Optional[Tuple[float, float]] = None,
    radius_m: int = DEFAULT_RADIUS_M,
) -> nx.MultiDiGraph:
    """Download a drivable road graph from OSM.

    Pass `place` for a named-boundary download, or `center` (lat, lon) +
    `radius_m` for a point-radius download (faster, good for demos). If neither
    is given, defaults to a downtown-Toronto point download that covers both
    Liberty Village and the Downtown Core.
    """
    import osmnx as ox  # imported lazily so the rest of the package needs no osmnx

    if place:
        graph = ox.graph_from_place(place, network_type="drive")
    else:
        lat, lon = center or DEFAULT_CENTER
        graph = ox.graph_from_point((lat, lon), dist=radius_m, network_type="drive")
    return graph


def enrich_graph(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Add/normalise all node and edge fields the simulation engine expects."""
    _enrich_nodes(graph)
    _enrich_edges(graph)
    _name_nodes_from_streets(graph)  # needs edge road_names, so run after edges
    build_edge_index(graph)
    return graph


def _enrich_nodes(graph: nx.MultiDiGraph) -> None:
    for node, data in graph.nodes(data=True):
        # OSMnx stores lon as x and lat as y. Mirror into lat/lon for clarity.
        if "x" in data:
            data["lon"] = float(data["x"])
        if "y" in data:
            data["lat"] = float(data["y"])
        data["node_id"] = node
        # 'name' is rarely present on OSM nodes; keep if available.
        data["name"] = first_value(data.get("name"))
        data["degree"] = graph.degree(node)


def _name_nodes_from_streets(graph: nx.MultiDiGraph) -> None:
    """Give each node a human-readable name from the streets that meet there.

    OSM almost never names intersections, so we synthesise one from the
    `road_name` of the incident edges (both directions):
      * 2+ distinct streets -> "King Street West & Spadina Avenue"
      * 1 street            -> "Lake Shore Boulevard East" (a midblock point)
      * 0 named streets     -> left as-is (usually None)
    Any real OSM node name already present is preserved.
    """
    for node, data in graph.nodes(data=True):
        if data.get("name"):  # keep a genuine OSM name if one exists
            continue
        counts: dict = {}
        for _, _, edata in graph.in_edges(node, data=True):
            _tally(counts, edata.get("road_name"))
        for _, _, edata in graph.out_edges(node, data=True):
            _tally(counts, edata.get("road_name"))
        if not counts:
            continue
        # Most common streets first, then alphabetical for determinism.
        ordered = sorted(counts, key=lambda n: (-counts[n], n))
        data["name"] = " & ".join(ordered[:2])


def _tally(counts: dict, name) -> None:
    name = first_value(name)
    if name:
        counts[name] = counts.get(name, 0) + 1


def _enrich_edges(graph: nx.MultiDiGraph) -> None:
    for u, v, k, data in graph.edges(keys=True, data=True):
        road_class = normalise_road_class(data.get("highway"))

        # ---- length (metres) -------------------------------------------
        length_m = to_float(data.get("length"))
        if length_m is None:
            length_m = _length_from_geometry(graph, u, v, data)
        length_m = float(length_m or 0.0)

        # ---- speed (km/h) ----------------------------------------------
        speed_kmh = to_float(data.get("maxspeed"))
        if speed_kmh is None or speed_kmh <= 0:
            speed_kmh = float(lookup(DEFAULT_SPEED_KMH, road_class))

        # ---- lanes -----------------------------------------------------
        lanes = to_float(data.get("lanes"))
        if lanes is None or lanes <= 0:
            lanes = float(lookup(DEFAULT_LANES, road_class))

        # ---- capacity (veh/hour) ---------------------------------------
        vphpl = lookup(VEHICLES_PER_HOUR_PER_LANE, road_class)
        capacity = lanes * vphpl
        # Floor capacity so no drivable edge ends up with 0 throughput, which
        # would make pressure infinite during simulation.
        if capacity <= 0:
            capacity = VEHICLES_PER_HOUR_PER_LANE["default"]

        # ---- travel time -----------------------------------------------
        bt = base_time_min(length_m, speed_kmh)

        # ---- one-way ---------------------------------------------------
        one_way = data.get("oneway")
        if isinstance(one_way, (list, tuple)):
            one_way = bool(one_way[0]) if one_way else None
        elif one_way is not None:
            one_way = bool(one_way)

        edge_id = make_edge_id(u, v, k)

        data.update(
            {
                "edge_id": edge_id,
                "from_node": u,
                "to_node": v,
                "road_name": first_value(data.get("name")),
                "road_class": road_class,
                "length_m": round(length_m, 2),
                "one_way": one_way,
                "speed_kmh": round(speed_kmh, 1),
                "lanes": lanes,
                "capacity": round(capacity, 1),
                "base_time_min": round(bt, 4),
                "current_time_min": round(bt, 4),
                "status": "open",
                "load": 0,
                "pressure": 0,
                "geometry": _geometry_to_latlon(data.get("geometry")),
            }
        )


def _length_from_geometry(graph, u, v, data) -> float:
    """Fall back to a straight-line endpoint distance if 'length' is missing."""
    from .config import haversine_m

    a, b = graph.nodes[u], graph.nodes[v]
    alat, alon = a.get("y", a.get("lat")), a.get("x", a.get("lon"))
    blat, blon = b.get("y", b.get("lat")), b.get("x", b.get("lon"))
    if None in (alat, alon, blat, blon):
        return 0.0
    return haversine_m(alat, alon, blat, blon)


def _geometry_to_latlon(geom):
    """Convert a shapely LineString to a JSON-friendly [[lat, lon], ...] list.

    Returns None when no geometry is present (the simulation engine can then
    fall back to drawing a straight line between the endpoints).
    """
    if geom is None:
        return None
    # Already a plain list (e.g. re-enriching an imported graph).
    if isinstance(geom, list):
        return geom
    try:
        # shapely LineString: coords are (lon, lat) pairs.
        return [[lat, lon] for lon, lat in geom.coords]
    except Exception:
        return None


def save_graph(graph: nx.MultiDiGraph) -> None:
    """Write the GraphML and JSON deliverables to data/graph/."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # JSON in the clean simulation format.
    export_graph_json(graph, JSON_PATH)

    # GraphML for easy NetworkX reload. GraphML can't store nested
    # lists/None, so write a sanitised copy (geometry is preserved in JSON).
    nx.write_graphml(_graphml_safe_copy(graph), GRAPHML_PATH)

    print(f"  wrote {JSON_PATH}")
    print(f"  wrote {GRAPHML_PATH}")


def _graphml_safe_copy(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Return a copy whose attributes are all GraphML-serialisable scalars."""
    g = nx.MultiDiGraph()
    g.graph["crs"] = graph.graph.get("crs", "epsg:4326")

    for node, data in graph.nodes(data=True):
        g.add_node(
            node,
            x=_scalar(data.get("x", data.get("lon"))),
            y=_scalar(data.get("y", data.get("lat"))),
            name=_scalar(data.get("name"), ""),
            degree=int(data.get("degree", 0) or 0),
        )

    for u, v, k, data in graph.edges(keys=True, data=True):
        ct = data.get("current_time_min")
        g.add_edge(
            u,
            v,
            key=k,
            edge_id=_scalar(data.get("edge_id"), ""),
            road_name=_scalar(data.get("road_name"), ""),
            road_class=_scalar(data.get("road_class"), ""),
            length_m=float(data.get("length_m", 0.0) or 0.0),
            one_way="" if data.get("one_way") is None else str(bool(data.get("one_way"))),
            speed_kmh=float(data.get("speed_kmh", 0.0) or 0.0),
            lanes=float(data.get("lanes", 0.0) or 0.0),
            capacity=float(data.get("capacity", 0.0) or 0.0),
            base_time_min=float(data.get("base_time_min", 0.0) or 0.0),
            current_time_min=("Infinity" if ct in (None, float("inf")) else float(ct)),
            status=_scalar(data.get("status"), "open"),
            load=float(data.get("load", 0) or 0),
            pressure=float(data.get("pressure", 0) or 0),
        )
    return g


def _scalar(value, default=""):
    """Coerce a value to a GraphML-safe scalar (no lists / None)."""
    value = first_value(value, default)
    if value is None:
        return default
    return value


def build_and_save(
    place: Optional[str] = None,
    center: Optional[Tuple[float, float]] = None,
    radius_m: int = DEFAULT_RADIUS_M,
) -> nx.MultiDiGraph:
    """Full pipeline: download -> enrich -> save. Returns the enriched graph."""
    print("Downloading road graph from OpenStreetMap ...")
    graph = download_graph(place=place, center=center, radius_m=radius_m)
    print(f"  raw graph: {graph.number_of_nodes():,} nodes, " f"{graph.number_of_edges():,} edges")
    print("Enriching edges ...")
    enrich_graph(graph)
    print("Saving ...")
    save_graph(graph)
    return graph


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Build the Toronto drive road graph.")
    p.add_argument("--place", help='OSM place name, e.g. "Toronto, Ontario, Canada".')
    p.add_argument(
        "--center",
        nargs=2,
        type=float,
        metavar=("LAT", "LON"),
        help="Point-radius download centre (lat lon).",
    )
    p.add_argument(
        "--radius",
        type=int,
        default=DEFAULT_RADIUS_M,
        help=f"Point-radius download radius in metres (default {DEFAULT_RADIUS_M}).",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help=f'Shortcut for --place "{DEFAULT_PLACE}" (whole city; slow).',
    )
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)
    place = args.place
    if args.full:
        place = DEFAULT_PLACE
    center = tuple(args.center) if args.center else None
    graph = build_and_save(place=place, center=center, radius_m=args.radius)

    from .routing import summarize_graph

    summarize_graph(graph)


if __name__ == "__main__":
    main()
