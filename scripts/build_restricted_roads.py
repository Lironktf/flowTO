#!/usr/bin/env python3
"""Derive the restricted-road closure guardrail from the Toronto Centreline (TCL).

Two road categories may never carry a *full* closure in the simulator:

  1. ``mto_prohibited``      — "Completely Prohibited" provincial highways
                               (MTO jurisdiction): the 400-series, the QEW, etc.
  2. ``municipal_expressway`` — City of Toronto expressways: the Gardiner, the
                               Don Valley Parkway, Allen Rd, Black Creek Dr.

Both surface in the TCL (``data/raw/RoadWarningData``) as ``FEATURE_CODE_DESC``
of ``Expressway`` / ``Expressway Ramp``; ``JURISDICTION`` (PROVINCE vs CITY OF
TORONTO) splits the two categories. The repo's own ``centreline_loader`` already
maps those feature codes to ``road_class == "motorway"``, so the drive graph's
motorway edges are exactly the restricted set — we only need the TCL to label
each edge with its category.

This script joins the (uncommitted, 93 MB) TCL GeoJSON against the committed
drive graph and writes a small artifact, ``data/graph/restricted_roads.json``,
that the API loads at runtime. Run it whenever the graph or TCL changes:

    python scripts/build_restricted_roads.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_TCL = os.path.join(
    REPO_ROOT, "data", "raw", "RoadWarningData", "Centreline - Version 2 - 4326.geojson"
)
DEFAULT_GRAPH = os.path.join(REPO_ROOT, "data", "graph", "toronto_drive_graph.json")
DEFAULT_OUT = os.path.join(REPO_ROOT, "data", "graph", "restricted_roads.json")

MTO = "mto_prohibited"
MUNICIPAL = "municipal_expressway"

# A provincial highway by name: the 400-series, Highway 2A/27, and the QEW. The
# TCL marks these JURISDICTION == PROVINCE; this pattern is the name-level twin
# used to label the drive graph's (OSM-named) motorway edges authoritatively.
_HIGHWAY_RE = re.compile(r"\bhighway\s*\d", re.I)


def _name_category(road_name: str | None) -> str | None:
    """Category from a graph road name, or ``None`` when the name is ambiguous."""
    if not road_name:
        return None
    name = road_name.lower()
    if _HIGHWAY_RE.search(name) or "queen elizabeth" in name:
        return MTO
    municipal_markers = (
        "gardiner",
        "don valley parkway",
        "allen",
        "black creek",
        "don roadway",
        "expressway",
        "parkway",
    )
    if any(marker in name for marker in municipal_markers):
        return MUNICIPAL
    return None


def _restricted_tcl_category(props: dict) -> str | None:
    desc = str(props.get("FEATURE_CODE_DESC") or "").strip().lower()
    if desc not in ("expressway", "expressway ramp"):
        return None
    jurisdiction = str(props.get("JURISDICTION") or "").strip().upper()
    if jurisdiction == "PROVINCE":
        return MTO
    if jurisdiction == "CITY OF TORONTO":
        return MUNICIPAL
    return None


def _edge_line(edge: dict, nodes: dict[int, tuple[float, float]]):
    from shapely.geometry import LineString

    geom = edge.get("geometry")
    if geom and len(geom) >= 2:
        return LineString([(lng, lat) for lat, lng in geom])
    a = nodes.get(edge.get("from"))
    b = nodes.get(edge.get("to"))
    if a and b:
        return LineString([(a[1], a[0]), (b[1], b[0])])  # nodes are (lat, lon)
    return None


def build(tcl_path: str, graph_path: str) -> dict:
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    with open(graph_path) as fh:
        graph = json.load(fh)
    nodes = {n["id"]: (n["lat"], n["lon"]) for n in graph["nodes"]}

    with open(tcl_path) as fh:
        tcl = json.load(fh)
    geoms: list = []
    cats: list[str] = []
    for feature in tcl["features"]:
        category = _restricted_tcl_category(feature.get("properties", {}))
        if not category or not feature.get("geometry"):
            continue
        try:
            geoms.append(shape(feature["geometry"]))
        except Exception:  # noqa: BLE001 — skip unparseable TCL geometry
            continue
        cats.append(category)
    if not geoms:
        raise SystemExit("No restricted segments found in the TCL file — wrong file?")
    tree = STRtree(geoms)

    edges: dict[str, dict] = {}
    counts = {MTO: 0, MUNICIPAL: 0}
    for edge in graph["edges"]:
        if edge.get("road_class") != "motorway":
            continue  # motorway == TCL Expressway per centreline_loader
        edge_id = edge.get("edge_id") or edge.get("id")
        road_name = edge.get("road_name")
        # Prefer the authoritative name rule; fall back to the nearest restricted
        # TCL segment for unnamed ramps and connectors.
        category = _name_category(road_name)
        if category is None:
            line = _edge_line(edge, nodes)
            if line is not None:
                nearest = tree.nearest(line)
                category = cats[int(nearest)]
        if category is None:
            category = MUNICIPAL  # an unplaceable motorway is still a restricted expressway
        counts[category] += 1
        edges[edge_id] = {"category": category, "label": road_name}

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "Toronto Centreline (TCL) — data/raw/RoadWarningData",
        "gate": "road_class == 'motorway' (TCL Expressway / Expressway Ramp)",
        "categories": {
            MTO: "Completely Prohibited highway (MTO / provincial jurisdiction)",
            MUNICIPAL: "Municipal expressway (City of Toronto)",
        },
        "counts": counts,
        "count": len(edges),
        "edges": edges,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tcl", default=DEFAULT_TCL, help="Toronto Centreline GeoJSON")
    parser.add_argument("--graph", default=DEFAULT_GRAPH, help="Drive graph JSON")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output artifact path")
    args = parser.parse_args()

    artifact = build(args.tcl, args.graph)
    with open(args.out, "w") as fh:
        json.dump(artifact, fh, indent=2)
    print(
        f"Wrote {artifact['count']} restricted edges "
        f"({artifact['counts'][MTO]} MTO, {artifact['counts'][MUNICIPAL]} municipal) "
        f"to {args.out}"
    )


if __name__ == "__main__":
    main()
