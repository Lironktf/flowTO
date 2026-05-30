"""
Shared configuration, defaults, and small geo helpers for the road graph layer.

Everything that needs to be agreed on across build / mutation / routing lives
here so there is a single source of truth for the simulation engine.
"""

from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# Defaults used to fill in fields OSM does not always provide.
#
# Keys are OSM `highway` classes (the road_class). We normalise a few common
# variants (e.g. "motorway_link" -> "motorway") before lookup; anything we
# don't recognise falls back to the "default" entry.
# ---------------------------------------------------------------------------

# Vehicles per hour per lane (free-flow saturation flow rate, roughly).
VEHICLES_PER_HOUR_PER_LANE = {
    "motorway": 1800,
    "trunk": 1200,
    "primary": 1200,
    "secondary": 900,
    "tertiary": 700,
    "residential": 400,
    "living_street": 400,
    "unclassified": 400,
    "service": 400,
    "default": 600,
}

# Estimated free-flow speed in km/h when OSM has no maxspeed tag.
DEFAULT_SPEED_KMH = {
    "motorway": 100,
    "trunk": 80,
    "primary": 60,
    "secondary": 50,
    "tertiary": 40,
    "residential": 30,
    "living_street": 20,
    "unclassified": 40,
    "service": 20,
    "default": 40,
}

# Estimated lane count (one direction) when OSM has no lanes tag.
DEFAULT_LANES = {
    "motorway": 3,
    "trunk": 3,
    "primary": 2,
    "secondary": 2,
    "tertiary": 1,
    "residential": 1,
    "living_street": 1,
    "unclassified": 1,
    "service": 1,
    "default": 1,
}

# BPR volume-delay (alpha, beta) per road class (P04). Global default is the
# US BPR 1964 (0.15, 4). Freeways tolerate higher v/c before breakdown; signal-
# controlled arterials degrade sooner (higher alpha). Tunable; the oracle test
# pins the global default to the AequilibraE/TNTP reference.
BPR_PARAMS = {
    "motorway": (0.15, 4.0),
    "trunk": (0.15, 4.0),
    "primary": (0.20, 4.0),
    "secondary": (0.20, 4.0),
    "tertiary": (0.25, 4.0),
    "residential": (0.25, 4.0),
    "default": (0.15, 4.0),
}

# Default place used by build_graph when none is supplied.
# Centred on downtown Toronto with a radius that comfortably covers both
# Liberty Village and the Downtown Core (used by the test script).
DEFAULT_CENTER = (43.6500, -79.3950)  # (lat, lon)
DEFAULT_RADIUS_M = 7000
DEFAULT_PLACE = "Toronto, Ontario, Canada"


def normalise_road_class(highway) -> str:
    """Collapse an OSM `highway` value (which may be a list, or a *_link
    variant) into one of the canonical classes used by the default tables."""
    if highway is None:
        return "default"
    # OSM tags are occasionally lists when a way has multiple classifications.
    if isinstance(highway, (list, tuple)):
        highway = highway[0] if highway else "default"
    highway = str(highway).strip().lower()
    if highway.endswith("_link"):
        highway = highway[: -len("_link")]
    return highway


def lookup(table: dict, road_class: str):
    """Look up a value in one of the default tables with a safe fallback."""
    return table.get(road_class, table["default"])


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    r = 6_371_000.0  # mean Earth radius in metres
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def base_time_min(length_m: float, speed_kmh: float) -> float:
    """Free-flow travel time in minutes for a segment.

    base_time_min = length_km / speed_kmh * 60
    """
    if speed_kmh <= 0:
        return float("inf")
    length_km = length_m / 1000.0
    return length_km / speed_kmh * 60.0


def first_value(value, default=None):
    """OSM attributes are sometimes lists; return a single representative value."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value


def to_float(value, default: Optional[float] = None) -> Optional[float]:
    """Best-effort float parse that tolerates lists and strings like '50 mph'."""
    value = first_value(value)
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    # Pull the first number out of a string such as "50" or "50 mph".
    num = ""
    for ch in str(value):
        if ch.isdigit() or (ch == "." and "." not in num):
            num += ch
        elif num:
            break
    try:
        return float(num)
    except ValueError:
        return default
