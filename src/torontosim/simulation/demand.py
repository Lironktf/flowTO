"""Demand-surge OD transform (P09) — the backend for the ``demand_surge`` op.

A surge changes **demand**, not the graph: it adds trips originating at a node
(or the node nearest a lng/lat) spread across the strongest existing OD
destinations — the real evening egress spine. This generalizes the BMO-Field
egress injection in ``demo/wc_surge.py`` into a reusable, op-driven helper so the
copilot and the Edit surge tool can model "add congestion near X" anywhere.

Deterministic: destinations are ranked then split by a fixed rule (no RNG).
"""

from __future__ import annotations

import math

from ..graph.config import haversine_m

# Compass direction → bearing range (degrees, 0=N, clockwise). Used to bias the
# surge's destinations when the op specifies directions.
_DIR_RANGES = {
    "n": (315.0, 45.0),
    "e": (45.0, 135.0),
    "s": (135.0, 225.0),
    "w": (225.0, 315.0),
}


def nearest_node(graph, lng: float, lat: float):
    """Graph node closest to (lng, lat), or None on an empty/degenerate graph."""
    best, best_d = None, float("inf")
    for n, d in graph.nodes(data=True):
        nlng, nlat = d.get("x"), d.get("y")
        if nlng is None or nlat is None:
            continue
        dist = haversine_m(lat, lng, nlat, nlng)
        if dist < best_d:
            best, best_d = n, dist
    return best


def _bearing(graph, origin, dest) -> float | None:
    o = graph.nodes[origin]
    d = graph.nodes[dest]
    if None in (o.get("x"), o.get("y"), d.get("x"), d.get("y")):
        return None
    dlng = (d["x"] - o["x"]) * math.cos(math.radians((o["y"] + d["y"]) / 2))
    dlat = d["y"] - o["y"]
    return (math.degrees(math.atan2(dlng, dlat)) + 360.0) % 360.0


def _in_directions(bearing: float | None, directions) -> bool:
    if bearing is None:
        return True
    for dr in directions:
        lo, hi = _DIR_RANGES.get(dr, (None, None))
        if lo is None:
            continue
        if lo < hi:
            if lo <= bearing < hi:
                return True
        elif bearing >= lo or bearing < hi:  # wraps through 0 (north)
            return True
    return False


def apply_demand_surge(
    od_matrix: list[dict],
    graph,
    *,
    node_id=None,
    lng: float | None = None,
    lat: float | None = None,
    amount: float = 5000.0,
    mode: str = "absolute",
    directions=None,
    k_dest: int = 40,
) -> list[dict]:
    """Return a NEW OD list with a surge injected at the resolved origin.

    ``amount`` is total trips added (``mode="absolute"``) or a fraction of the
    current total demand (``mode="relative"``). Trips spread across the top
    ``k_dest`` existing destinations (optionally biased to ``directions``).
    Falls back to the unchanged OD if the origin/destinations can't be resolved.
    """
    origin = node_id
    if origin is None and lng is not None and lat is not None:
        origin = nearest_node(graph, lng, lat)
    if origin is None or origin not in graph:
        return list(od_matrix)

    dest_weight: dict = {}
    for e in od_matrix:
        dest_weight[e["destination"]] = dest_weight.get(e["destination"], 0.0) + e["trips"]
    ranked = sorted(dest_weight, key=lambda d: (-dest_weight[d], str(d)))
    if directions:
        biased = [d for d in ranked if _in_directions(_bearing(graph, origin, d), directions)]
        ranked = biased or ranked  # fall back to all if the bias matches nothing
    dests = [d for d in ranked if d != origin][:k_dest]
    if not dests:
        return list(od_matrix)

    total = amount if mode != "relative" else amount * sum(dest_weight.values())
    per = total / len(dests)
    return list(od_matrix) + [{"origin": origin, "destination": d, "trips": per} for d in dests]
