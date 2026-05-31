"""Apply front-end "demand change" interventions to the OD trip matrix.

A surge/relief is a *demand-side* edit: the user drops a pin on an intersection
and injects (or relieves) trips radiating out along the streets leaving it in the
chosen compass directions. Unlike the graph mutations (close_edge, …) this does
NOT touch the network topology — it edits the origin→destination trip list.

It is applied to the *grounded* OD matrix (after ``build_grounded_od``), NOT to
the pre-OD node demand: the ODME grounding step re-normalizes magnitude to match
observed counts, so a pre-OD bump only shifts the distribution and its *volume*
is washed out. Editing the OD directly — with ``auto_calibrate=False`` in the
simulator — means injected trips survive into the assignment.

A surge adds OD pairs ``anchor → destination`` for real attractor nodes lying in
the chosen compass directions (so the trips route out along those streets and
propagate through the network); relief scales down existing trips originating at
the anchor. Geometry helpers are a Python port of the front-end direction logic
in ``frontend/src/api/graph.ts`` (``bearingDeg`` / ``compassOf``).

Wire op (emitted by the front-end ``interventionsFromObjects``):

    {"op": "demand_change", "edge_id": str, "directions": ["n","e","s","w" subset],
     "amount": float (signed; negative = relief), "mode": "absolute"|"relative",
     "lng": float, "lat": float}
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from ..graph.config import haversine_m

Compass = str  # "n" | "e" | "s" | "w"
_CARDINALS = ("n", "e", "s", "w")


# ── geometry helpers (ports of the front-end) ───────────────────────────────


def bearing_deg(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Initial compass bearing (degrees, 0=N, clockwise) of the ray a→b."""
    to_rad = math.pi / 180.0
    phi1 = a_lat * to_rad
    phi2 = b_lat * to_rad
    dlon = (b_lon - a_lon) * to_rad
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return math.atan2(y, x) * 180.0 / math.pi


def compass_of(bearing: float) -> Compass:
    """Bucket a compass bearing into the nearest cardinal direction."""
    b = (bearing % 360.0 + 360.0) % 360.0
    if b >= 315.0 or b < 45.0:
        return "n"
    if b < 135.0:
        return "e"
    if b < 225.0:
        return "s"
    return "w"


def _node_latlon(graph, node) -> Optional[tuple]:
    data = graph.nodes.get(node)
    if data is None:
        return None
    lat = data.get("y", data.get("lat"))
    lon = data.get("x", data.get("lon"))
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def streets_by_direction(graph, node_id) -> Dict[Compass, dict]:
    """Streets leaving ``node_id``, keyed by the cardinal direction they head in.

    Mirrors the front-end: orient each incident edge's polyline to start at the
    anchor, bucket its first segment's bearing to N/E/S/W, and keep the longest
    street per direction. Returns ``{dir: {edge_id, neighbor_node, road_name}}``.
    """
    out: Dict[Compass, dict] = {}
    seen: set = set()

    # Edges leaving the node keep their stored geometry (anchor→v); edges
    # arriving (w→anchor) are reversed so they too read outward from the anchor.
    incident = []
    for _u, v, _k, data in graph.out_edges(node_id, keys=True, data=True):
        incident.append((data, v, False))
    for u, _v, _k, data in graph.in_edges(node_id, keys=True, data=True):
        incident.append((data, u, True))

    for data, neighbor, reverse in incident:
        eid = data.get("edge_id")
        if eid in seen:
            continue
        geom = data.get("geometry")
        if not (isinstance(geom, list) and len(geom) >= 2):
            continue
        seen.add(eid)
        g = list(reversed(geom)) if reverse else geom
        a_lat, a_lon = g[0][0], g[0][1]
        b_lat, b_lon = g[1][0], g[1][1]
        d = compass_of(bearing_deg(a_lat, a_lon, b_lat, b_lon))
        npts = len(g)
        cur = out.get(d)
        if cur is None or npts > cur["npts"]:
            out[d] = {
                "edge_id": eid,
                "neighbor_node": neighbor,
                "road_name": data.get("road_name"),
                "npts": npts,
            }
    return out


def resolve_anchor_node(graph, *, edge_id=None, lng=None, lat=None):
    """Resolve the intersection a surge anchors at.

    Mirrors the front-end: of the clicked edge's two endpoints, the one nearest
    the click point. Falls back to the nearest node when no usable edge_id.
    """
    from ..graph.routing import get_edge_key, get_nearest_node

    if edge_id:
        u = v = None
        try:
            u, v, _k = get_edge_key(graph, edge_id)
        except Exception:  # noqa: BLE001 — unknown edge_id falls back below
            u = v = None
        if u is not None and v is not None and lat is not None and lng is not None:
            du = _node_dist(graph, u, lat, lng)
            dv = _node_dist(graph, v, lat, lng)
            return u if du <= dv else v
        if u is not None:
            return u

    if lat is not None and lng is not None:
        try:
            return get_nearest_node(graph, float(lat), float(lng))  # lat-first!
        except Exception:  # noqa: BLE001
            return None
    return None


def _node_dist(graph, node, lat, lon) -> float:
    ll = _node_latlon(graph, node)
    if ll is None:
        return math.inf
    return haversine_m(float(lat), float(lon), ll[0], ll[1])


# ── the public entry point ───────────────────────────────────────────────────

# How many attractor destinations a single surge spreads its trips across, and
# the geographic bounds on an injected trip (km) — mirrors the OD gravity model.
_SURGE_FANOUT = 30
_MIN_TRIP_KM = 0.4
_MAX_TRIP_KM = 25.0


def apply_od_changes(graph, od: List[dict], surge_ops: List[dict]) -> List[dict]:
    """Return a COPY of the OD list with the ``demand_change`` ops applied.

    A **surge** (amount > 0) injects ``amount`` trips from the anchor to real
    attractor nodes (drawn from the OD's existing destinations) that lie in the
    chosen compass directions, weighted toward nearer ones (gravity-like) so they
    route out along those streets. **Relief** (amount < 0) scales down trips that
    originate at the anchor, removing up to ``|amount|`` trips (floored at 0).
    ``mode="relative"`` treats ``amount`` as a signed fraction of the trips
    currently touching the anchor instead of an absolute trip count.
    """
    if not surge_ops:
        return od
    out = [dict(p) for p in od]

    for op in surge_ops:
        try:
            amount = float(op.get("amount") or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount == 0.0:
            continue
        mode = str(op.get("mode") or "absolute").strip().lower()
        dirs = [d for d in (op.get("directions") or []) if d in _CARDINALS]

        anchor = resolve_anchor_node(
            graph, edge_id=op.get("edge_id"), lng=op.get("lng"), lat=op.get("lat")
        )
        if anchor is None:
            continue
        a_ll = _node_latlon(graph, anchor)
        if a_ll is None:
            continue

        if amount > 0 or mode == "relative":
            # Resolve how many trips to inject (relative → fraction of trips
            # currently touching the anchor; absolute → the amount itself).
            if mode == "relative":
                touching = sum(p["trips"] for p in out if anchor in (p["origin"], p["destination"]))
                inject = touching * amount  # signed
            else:
                inject = amount

            if inject > 0:
                _inject_surge(graph, out, anchor, a_ll, dirs, inject)
            elif inject < 0:
                _apply_relief(out, anchor, -inject)
        else:  # absolute relief
            _apply_relief(out, anchor, -amount)
    return out


def _inject_surge(graph, od, anchor, a_ll, dirs, inject: float) -> None:
    """Add ``inject`` trips from ``anchor`` to nearby attractors in ``dirs``."""
    cands = []
    for dn in {p["destination"] for p in od}:
        if dn == anchor:
            continue
        d_ll = _node_latlon(graph, dn)
        if d_ll is None:
            continue
        dist = haversine_m(a_ll[0], a_ll[1], d_ll[0], d_ll[1]) / 1000.0
        if dist < _MIN_TRIP_KM or dist > _MAX_TRIP_KM:
            continue
        if dirs and compass_of(bearing_deg(a_ll[0], a_ll[1], d_ll[0], d_ll[1])) not in dirs:
            continue
        cands.append((dn, dist))
    if not cands:
        return
    cands.sort(key=lambda x: x[1])
    cands = cands[:_SURGE_FANOUT]
    wsum = sum(1.0 / (1.0 + d) for _, d in cands)
    for dn, dist in cands:
        w = (1.0 / (1.0 + dist)) / wsum
        od.append({"origin": anchor, "destination": dn, "trips": inject * w})


def _apply_relief(od, anchor, reduce: float) -> None:
    """Scale down trips originating at ``anchor`` to remove up to ``reduce``."""
    orig = [p for p in od if p["origin"] == anchor]
    total = sum(p["trips"] for p in orig)
    if total <= 0:
        return
    frac = max(0.0, 1.0 - reduce / total)
    for p in orig:
        p["trips"] *= frac
