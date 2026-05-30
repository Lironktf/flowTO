"""
Shared feature engineering for the demand model.

CRITICAL: training (`train_demand_model.py`) and inference
(`predict_node_demand.py`) both build their feature rows here, so the columns
can never drift between the two. If you add a feature, add it once, in
FEATURE_ORDER and `build_feature_row`, and both sides stay in sync.

A "row" describes one (node, time-context) pair:

    location (lat, lon, degree, distance-to-downtown, near-highway, road class)
  + time     (hour, day-of-week, month, is-weekend, weather)
  -> vehicle_count   (the target, supplied only at training time)
"""

from __future__ import annotations

from typing import Dict

from ..graph.config import haversine_m

# Downtown reference point (roughly the financial core / Union area). Used for
# the `distance_to_downtown` feature and for time-of-day OD biasing.
DOWNTOWN_LATLON = (43.6510, -79.3810)

# Ordinal rank of OSM road classes (higher = bigger road). Used both as the
# `road_class_context` feature and to decide `near_highway`.
ROAD_CLASS_RANK = {
    "motorway": 6,
    "trunk": 5,
    "primary": 4,
    "secondary": 3,
    "tertiary": 2,
    "unclassified": 1,
    "residential": 1,
    "living_street": 1,
    "service": 1,
}
DEFAULT_ROAD_RANK = 1
HIGHWAY_CLASSES = {"motorway", "trunk"}

# Weather -> integer code (ordinal-ish: clear best, snow worst for driving).
WEATHER_CODE = {
    "clear": 0,
    "cloud": 1,
    "cloudy": 1,
    "overcast": 1,
    "rain": 2,
    "fog": 2,
    "snow": 3,
}
DEFAULT_WEATHER_CODE = 0

# A speed/throughput penalty applied during simulation for bad weather.
# (Demand also shifts a little, but the biggest physical effect is on speed.)
WEATHER_SPEED_FACTOR = {
    "clear": 1.0,
    "cloud": 1.0,
    "overcast": 1.0,
    "rain": 0.9,
    "fog": 0.85,
    "snow": 0.75,
}

# The exact, ordered list of model input columns.
FEATURE_ORDER = [
    "lat",
    "lon",
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "weather_code",
    "road_degree",
    "distance_to_downtown",
    "near_highway",
    "road_class_rank",
]


def weather_code(weather) -> int:
    if weather is None:
        return DEFAULT_WEATHER_CODE
    return WEATHER_CODE.get(str(weather).strip().lower(), DEFAULT_WEATHER_CODE)


def weather_speed_factor(weather) -> float:
    if weather is None:
        return 1.0
    return WEATHER_SPEED_FACTOR.get(str(weather).strip().lower(), 1.0)


def season_from_month(month: int) -> str:
    """Northern-hemisphere season for a month (1-12)."""
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "fall"


def normalize_time_context(tc: dict) -> dict:
    """Fill in derivable fields so callers can pass a partial context.

    Required: hour. Everything else gets a sensible default.
      - day_of_week: 0=Mon .. 6=Sun (default 2 = Wednesday)
      - month: 1-12 (default 6)
      - is_weekend: derived from day_of_week if absent
      - season: derived from month if absent
      - weather: default 'clear'
    """
    out = dict(tc or {})
    out["hour"] = int(out.get("hour", 8))
    out["day_of_week"] = int(out.get("day_of_week", 2))
    out["month"] = int(out.get("month", 6))
    if "is_weekend" not in out:
        out["is_weekend"] = 1 if out["day_of_week"] >= 5 else 0
    out["is_weekend"] = int(out["is_weekend"])
    if "season" not in out or not out["season"]:
        out["season"] = season_from_month(out["month"])
    out["weather"] = out.get("weather") or "clear"
    return out


# ---------------------------------------------------------------------------
# Static (time-independent) node features, computed once per graph.
# ---------------------------------------------------------------------------


def compute_static_node_features(graph) -> Dict[object, dict]:
    """Return {node_id: {lat, lon, road_degree, distance_to_downtown,
    near_highway, road_class_rank, name}} for every node.

    These depend only on the graph geometry/topology, so the simulator caches
    them and reuses across every time context.
    """
    dlat, dlon = DOWNTOWN_LATLON
    feats: Dict[object, dict] = {}
    for node, data in graph.nodes(data=True):
        lat = data.get("lat", data.get("y"))
        lon = data.get("lon", data.get("x"))
        if lat is None or lon is None:
            # Skip nodes with no geometry; they can't be featurised or routed.
            continue
        # Inspect incident edges for the dominant road class / highway adjacency.
        best_rank = DEFAULT_ROAD_RANK
        near_hw = 0
        for _, _, ed in graph.in_edges(node, data=True):
            best_rank, near_hw = _accumulate_class(ed, best_rank, near_hw)
        for _, _, ed in graph.out_edges(node, data=True):
            best_rank, near_hw = _accumulate_class(ed, best_rank, near_hw)

        feats[node] = {
            "lat": float(lat),
            "lon": float(lon),
            "road_degree": int(data.get("degree", graph.degree(node))),
            "distance_to_downtown": haversine_m(lat, lon, dlat, dlon) / 1000.0,
            "near_highway": int(near_hw),
            "road_class_rank": int(best_rank),
            "name": data.get("name"),
        }
    return feats


def _accumulate_class(edge_data, best_rank, near_hw):
    rc = edge_data.get("road_class")
    rank = ROAD_CLASS_RANK.get(rc, DEFAULT_ROAD_RANK)
    if rank > best_rank:
        best_rank = rank
    if rc in HIGHWAY_CLASSES:
        near_hw = 1
    return best_rank, near_hw


def build_feature_row(static_feat: dict, tc: dict) -> list:
    """Assemble one model input row (in FEATURE_ORDER) from a node's static
    features plus a normalised time context."""
    return [
        static_feat["lat"],
        static_feat["lon"],
        tc["hour"],
        tc["day_of_week"],
        tc["month"],
        tc["is_weekend"],
        weather_code(tc["weather"]),
        static_feat["road_degree"],
        static_feat["distance_to_downtown"],
        static_feat["near_highway"],
        static_feat["road_class_rank"],
    ]


def is_rush_hour(hour: int) -> bool:
    return hour in (7, 8, 9, 16, 17, 18, 19)


def rush_factor(hour: int, is_weekend: int) -> float:
    """A smooth-ish demand multiplier by hour of day.

    Weekday mornings/evenings peak; overnight is quiet; weekends are flatter
    with a midday/evening bump. Used by the heuristic demand model and the
    synthetic training-data generator.
    """
    if is_weekend:
        # Flatter, peaks late morning and evening.
        base = {
            0: 0.4,
            1: 0.3,
            2: 0.25,
            3: 0.2,
            4: 0.2,
            5: 0.25,
            6: 0.35,
            7: 0.5,
            8: 0.65,
            9: 0.8,
            10: 0.95,
            11: 1.0,
            12: 1.0,
            13: 0.95,
            14: 0.9,
            15: 0.9,
            16: 0.95,
            17: 1.0,
            18: 1.0,
            19: 0.95,
            20: 0.8,
            21: 0.7,
            22: 0.6,
            23: 0.5,
        }
    else:
        base = {
            0: 0.3,
            1: 0.2,
            2: 0.18,
            3: 0.18,
            4: 0.25,
            5: 0.45,
            6: 0.75,
            7: 1.15,
            8: 1.4,
            9: 1.1,
            10: 0.85,
            11: 0.85,
            12: 0.9,
            13: 0.88,
            14: 0.9,
            15: 1.0,
            16: 1.3,
            17: 1.5,
            18: 1.4,
            19: 1.05,
            20: 0.8,
            21: 0.65,
            22: 0.5,
            23: 0.38,
        }
    return base.get(int(hour) % 24, 0.7)
