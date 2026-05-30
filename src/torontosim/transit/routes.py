"""GTFS route geometry → colored lines by mode (P08).

Produces per-route LineStrings tagged with GTFS ``route_type`` so the frontend
colors by mode. Operates on plain records (fixture-testable); ``gtfs_kit``
(`geometrize_shapes`) is the production path. Includes a small demo transit set
(509 Harbourfront / 511 Bathurst) so the overlay renders without a fetched feed.
"""

from __future__ import annotations

# GTFS route_type → display mode (research/02).
ROUTE_TYPE_MODE = {
    0: "streetcar",  # tram / light rail
    1: "subway",
    2: "rail",  # GO
    3: "bus",
    109: "air-rail",  # UP Express (extended type)
}


def route_geometries(routes: list[dict]) -> list[dict]:
    """Normalize route records → ``{route_id, short_name, route_type, mode, path}``."""
    out = []
    for r in routes:
        rtype = int(r.get("route_type", 3))
        path = r.get("path") or r.get("geometry")
        if not path:
            continue
        out.append(
            {
                "route_id": r.get("route_id"),
                "short_name": r.get("route_short_name") or r.get("short_name"),
                "route_type": rtype,
                "mode": ROUTE_TYPE_MODE.get(rtype, "bus"),
                "agency": r.get("agency", "ttc"),
                "path": [[float(c[0]), float(c[1])] for c in path],
            }
        )
    return out


# Demo transit set (509 Harbourfront / 511 Bathurst), matching design corridors.
DEMO_ROUTES = [
    {
        "route_id": "509",
        "route_short_name": "509",
        "route_type": 0,
        "agency": "ttc",
        "path": [[-79.412, 43.6348], [-79.404, 43.636], [-79.396, 43.6372]],
    },
    {
        "route_id": "511",
        "route_short_name": "511",
        "route_type": 0,
        "agency": "ttc",
        "path": [[-79.403, 43.6362], [-79.4035, 43.6428], [-79.404, 43.6492]],
    },
]


def demo_routes() -> list[dict]:
    return route_geometries(DEMO_ROUTES)


def demo_trajectories(*, headway_s: int = 360, start_s: int = 14 * 3600, end_s: int = 20 * 3600):
    """Synthesize scheduled trajectories along the demo routes (no feed needed).

    A vehicle departs each route every ``headway_s`` and traverses the route over
    a fixed run time, producing TripsLayer-ready ``{path, timestamps}``.
    """
    from .trajectories import build_trip_set

    trips = []
    for route in DEMO_ROUTES:
        path = route["path"]
        run_time = 600  # 10 min end-to-end
        depart = start_s
        n = 0
        while depart <= end_s:
            stop_times = []
            for i, (lng, lat) in enumerate(path):
                frac = i / max(1, len(path) - 1)
                stop_times.append(
                    {
                        "stop_sequence": i,
                        "arrival_time": int(depart + frac * run_time),
                        "lng": lng,
                        "lat": lat,
                    }
                )
            trips.append(
                {
                    "trip_id": f"{route['route_id']}_{n}",
                    "route_id": route["route_id"],
                    "stop_times": stop_times,
                }
            )
            depart += headway_s
            n += 1
    return build_trip_set(trips, route_type=0, agency="ttc")
