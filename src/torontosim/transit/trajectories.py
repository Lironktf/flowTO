"""Schedule → vehicle trajectories for TripsLayer (P08).

For a service date, each active trip's ``stop_times`` become a
``{path:[[lng,lat]…], timestamps:[secs_since_midnight]}`` record. Timestamps are
**seconds since midnight** (small floats → no TripsLayer float32 jitter) and may
exceed 86400 for after-midnight service (no wrap). Works on plain dicts so it is
fixture-testable without a full GTFS feed; ``gtfs_kit`` is the production loader.
"""

from __future__ import annotations


def parse_gtfs_time(value: str) -> int:
    """``HH:MM:SS`` → seconds since midnight (>24h allowed; never wraps)."""
    h, m, s = (int(p) for p in str(value).split(":"))
    return h * 3600 + m * 60 + s


def build_trajectory(stop_times: list[dict]) -> dict:
    """Build one trip's trajectory from its stop_times.

    Each ``stop_times`` row: ``{stop_sequence, arrival_time, lng, lat}``
    (``arrival_time`` is ``HH:MM:SS`` or already an int of seconds). Returns
    ``{path, timestamps}`` ordered by stop_sequence with monotonic timestamps.
    """
    rows = sorted(stop_times, key=lambda r: int(r["stop_sequence"]))
    path: list[list[float]] = []
    timestamps: list[int] = []
    for r in rows:
        t = r["arrival_time"]
        secs = t if isinstance(t, (int, float)) else parse_gtfs_time(t)
        # Enforce monotonic non-decreasing timestamps (GTFS is, but be safe).
        if timestamps and secs < timestamps[-1]:
            secs = timestamps[-1]
        path.append([float(r["lng"]), float(r["lat"])])
        timestamps.append(int(secs))
    return {"path": path, "timestamps": timestamps}


def interpolate_position(traj: dict, t: float) -> list[float] | None:
    """Vehicle position [lng, lat] at time ``t`` (secs since midnight).

    Returns ``None`` if the trip isn't active at ``t``. Linear interpolation
    between the bracketing waypoints (so the point lies on the path segment).
    """
    ts = traj["timestamps"]
    path = traj["path"]
    if not ts or t < ts[0] or t > ts[-1]:
        return None
    for i in range(len(ts) - 1):
        if ts[i] <= t <= ts[i + 1]:
            span = ts[i + 1] - ts[i]
            frac = 0.0 if span == 0 else (t - ts[i]) / span
            a, b = path[i], path[i + 1]
            return [a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac]
    return path[-1]


def build_trip_set(trips: list[dict], *, route_type: int, agency: str) -> list[dict]:
    """Build tagged trajectories for many trips (each with ``stop_times``)."""
    out = []
    for trip in trips:
        traj = build_trajectory(trip["stop_times"])
        if len(traj["path"]) >= 2:
            out.append(
                {
                    "trip_id": trip.get("trip_id"),
                    "route_id": trip.get("route_id"),
                    "route_type": route_type,
                    "agency": agency,
                    **traj,
                }
            )
    return out
