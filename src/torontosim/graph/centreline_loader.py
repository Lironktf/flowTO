"""Centreline → road graph loader (P02, behind ``graph_source=centreline``).

Builds a directed ``MultiDiGraph`` from the official Toronto Centreline (TCL)
segments + the Intersection file, conforming to the **canonical schema**
(``graph.schema``) so routing/mutations/sim treat it identically to the OSMnx
baseline. TCL ``CENTRELINE_ID`` is preserved on every edge so TMC counts and
road restrictions (which key on it) can be joined later.

The core builders operate on **lists of record dicts** (case-insensitive field
access) so tests run on a tiny committed fixture without a parquet store;
``load_from_parquet`` is the thin production wrapper over the P01 bake.
"""

from __future__ import annotations

import networkx as nx

from . import schema
from .config import (
    DEFAULT_LANES,
    DEFAULT_SPEED_KMH,
    VEHICLES_PER_HOUR_PER_LANE,
    base_time_min,
    haversine_m,
    lookup,
)
from .routing import build_edge_index, make_edge_id

# TCL FEATURE_CODE_DESC -> our config road_class. Anything not here is dropped
# (rivers, walkways, rail, admin lines) so the graph is drivable roads only.
TCL_CLASS_TO_ROAD_CLASS = {
    "expressway": "motorway",
    "expressway ramp": "motorway",
    "major arterial": "primary",
    "major arterial ramp": "primary",
    "minor arterial": "secondary",
    "collector": "tertiary",
    "collector ramp": "tertiary",
    "local": "residential",
    "laneway": "service",
    "access road": "service",
    "busway": "secondary",
}


def _get(rec: dict, *names, default=None):
    """Case-insensitive field access (TCL is UPPERCASE; parquet may lowercase)."""
    lower = {k.lower(): v for k, v in rec.items()}
    for n in names:
        if n.lower() in lower and lower[n.lower()] not in (None, ""):
            return lower[n.lower()]
    return default


def _coords_latlon(geom) -> list[list[float]] | None:
    """Normalize a geometry to ``[[lat, lon], ...]`` (Liron's stored form)."""
    if geom is None:
        return None
    # shapely geometry
    coords = getattr(geom, "coords", None)
    if coords is not None:
        return [[float(y), float(x)] for x, y in coords]  # shapely is (x=lng,y=lat)
    if isinstance(geom, str):
        try:
            from shapely import wkt

            g = wkt.loads(geom)
            return [[float(y), float(x)] for x, y in g.coords]
        except Exception:  # noqa: BLE001
            return None
    if isinstance(geom, dict):  # GeoJSON Point or LineString
        cs = geom.get("coordinates")
        if cs:
            # Point: flat [lng, lat]; LineString: [[lng, lat], ...].
            if isinstance(cs[0], (int, float)):
                return [[float(cs[1]), float(cs[0])]]
            return [[float(c[1]), float(c[0])] for c in cs]
    if isinstance(geom, (list, tuple)) and geom and isinstance(geom[0], (list, tuple)):
        # already a coordinate list; assume [lng, lat]
        return [[float(c[1]), float(c[0])] for c in geom]
    return None


def _polyline_length_m(latlon: list[list[float]]) -> float:
    total = 0.0
    for a, b in zip(latlon, latlon[1:]):
        total += haversine_m(a[0], a[1], b[0], b[1])
    return total


def _road_class(rec: dict) -> str | None:
    desc = _get(rec, "FEATURE_CODE_DESC", "feature_code_desc", "road_class")
    if desc is None:
        return None
    return TCL_CLASS_TO_ROAD_CLASS.get(str(desc).strip().lower())


def build_nodes(intersection_records) -> dict:
    """Intersection file -> ``{intersection_id: (lon, lat)}`` (deduped)."""
    nodes: dict = {}
    for rec in intersection_records:
        iid = _get(rec, "INTERSECTION_ID", "intersection_id")
        if iid is None:
            continue
        iid = int(iid) if str(iid).isdigit() else iid
        if iid in nodes:
            continue  # multi-level intersection -> keep first (planar dedupe)
        geom = _get(rec, "geometry", "geometry_wkt", "geom")
        ll = _coords_latlon(geom)
        if ll:
            lat, lon = ll[0][0], ll[0][1]
        else:
            lat = _get(rec, "latitude", "lat", "y")
            lon = _get(rec, "longitude", "lon", "lng", "x")
            if lat is None or lon is None:
                continue
            lat, lon = float(lat), float(lon)
        nodes[iid] = (lon, lat)
    return nodes


def _oneway_direction(rec: dict) -> int:
    """ONEWAY_DIR_CODE: 0 two-way, 1 from->to, -1 to->from."""
    code = _get(rec, "ONEWAY_DIR_CODE", "oneway_dir_code", default=0)
    try:
        return int(float(code))
    except (TypeError, ValueError):
        return 0


def build_centreline_graph(
    tcl_records,
    intersection_records,
    *,
    bridges=None,
) -> nx.MultiDiGraph:
    """Build a canonical-schema graph from TCL + Intersection records.

    ``bridges`` (optional): records with a centreline/location key and
    ``VERT_CLEAR`` to attach as an edge height attribute.
    """
    g = nx.MultiDiGraph()
    node_xy = build_nodes(intersection_records)
    for iid, (lon, lat) in node_xy.items():
        g.add_node(iid, x=lon, y=lat)

    confidence = {
        "lanes": "default",
        "speed_kmh": "default",
        "capacity": "default",
        "one_way": "observed",  # directionality comes straight from TCL
    }

    for rec in tcl_records:
        road_class = _road_class(rec)
        if road_class is None:
            continue  # not a drivable road class — skip
        a = _get(rec, "FROM_INTERSECTION_ID", "from_intersection_id")
        b = _get(rec, "TO_INTERSECTION_ID", "to_intersection_id")
        if a is None or b is None:
            continue
        a = int(a) if str(a).isdigit() else a
        b = int(b) if str(b).isdigit() else b
        if a not in node_xy or b not in node_xy:
            continue  # endpoint not in intersection file — skip (honest)

        geom = _coords_latlon(_get(rec, "geometry", "geometry_wkt", "geom"))
        if geom and len(geom) >= 2:
            length_m = _polyline_length_m(geom)
        else:
            (alon, alat), (blon, blat) = node_xy[a], node_xy[b]
            length_m = haversine_m(alat, alon, blat, blon)
            geom = [[alat, alon], [blat, blon]]
        if length_m <= 0:
            continue

        speed = float(lookup(DEFAULT_SPEED_KMH, road_class))
        lanes = float(lookup(DEFAULT_LANES, road_class))
        vphpl = lookup(VEHICLES_PER_HOUR_PER_LANE, road_class)
        capacity = max(lanes * vphpl, VEHICLES_PER_HOUR_PER_LANE["default"])
        bt = base_time_min(length_m, speed)
        cid = _get(rec, "CENTRELINE_ID", "centreline_id")
        name = _get(rec, "LINEAR_NAME_FULL", "linear_name_full", "road_name")
        direction = _oneway_direction(rec)

        def _add(u, v, geometry):
            eid = make_edge_id(u, v, 0)
            edge = schema.make_edge(
                edge_id=eid,
                from_node=u,
                to_node=v,
                road_class=road_class,
                length_m=length_m,
                speed_kmh=speed,
                lanes=lanes,
                capacity=capacity,
                base_time_min=bt,
                road_name=name,
                one_way=(direction != 0),
                geometry=geometry,
                confidence=dict(confidence),
                centreline_id=cid,
            )
            g.add_edge(u, v, key=0, **edge)

        if direction == 0:
            _add(a, b, geom)
            _add(b, a, list(reversed(geom)))
        elif direction == -1:
            _add(b, a, list(reversed(geom)))
        else:  # 1 or anything else -> digitized direction
            _add(a, b, geom)

    if bridges:
        _attach_bridge_clearances(g, bridges)

    build_edge_index(g)
    return g


def _attach_bridge_clearances(g: nx.MultiDiGraph, bridges) -> None:
    """Best-effort: tag edges sharing a centreline_id with a bridge's VERT_CLEAR."""
    by_cid: dict = {}
    for br in bridges:
        cid = _get(br, "CENTRELINE_ID", "centreline_id")
        vc = _get(br, "VERT_CLEAR", "vert_clear")
        if cid is not None and vc is not None:
            try:
                by_cid[cid] = float(vc)
            except (TypeError, ValueError):
                continue
    if not by_cid:
        return
    for _u, _v, data in g.edges(data=True):
        cid = data.get("centreline_id")
        if cid in by_cid:
            data["vert_clear_m"] = by_cid[cid]
            data["confidence"]["vert_clear_m"] = "observed"


def load_from_parquet(parquet_dir: str) -> nx.MultiDiGraph:
    """Production wrapper: read baked TCL/intersection/bridges parquet (P01)."""
    import os

    import pyarrow.parquet as pq

    def _rows(name):
        path = os.path.join(parquet_dir, f"{name}.parquet")
        if not os.path.exists(path):
            return []
        return pq.read_table(path).to_pylist()

    return build_centreline_graph(
        _rows("centreline"),
        _rows("intersections"),
        bridges=_rows("bridges") or None,
    )
