"""GTFS-zip reader → route LineStrings + per-trip trajectories (P08, W4).

The hand-authored demo set in ``routes.py`` is fine for a render without a feed,
but this reads a **real GTFS feed** (TTC / GO / UP) into the same shapes the
overlay already consumes:

  * ``route_lines``  → per-route ``{route_id, short_name, route_type, mode,
    agency, path}`` (geometry from ``shapes.txt``, mirroring gtfs_kit's
    ``geometrize_shapes``; falls back to the stop sequence when a feed ships no
    shapes).
  * ``trip_trajectories`` → per-trip ``{path, timestamps}`` via the existing
    ``trajectories.build_trajectory`` contract (seconds since midnight,
    float32-safe, **no >86400 wrap** for after-midnight service).

Works on a GTFS **zip** or an unpacked **directory** (the committed fixture is a
directory so it stays diffable). ``gtfs_kit`` is the optional production
accelerator (new ``transit`` extra); the stdlib path here keeps tests hermetic.
Feeds are cached to ``data/transit/{agency}_{date}.json`` so the API serves them
without re-reading the zip.
"""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile

from .routes import ROUTE_TYPE_MODE, route_geometries
from .trajectories import build_trajectory


def read_table(src, name: str) -> list[dict]:
    """Read one GTFS table (``<name>.txt``) from a zip or directory → rows.

    Returns ``[]`` if the table is absent (optional GTFS files like shapes.txt).
    """
    src = str(src)
    if os.path.isdir(src):
        path = os.path.join(src, f"{name}.txt")
        if not os.path.exists(path):
            return []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    with zipfile.ZipFile(src) as zf:
        fn = f"{name}.txt"
        if fn not in zf.namelist():
            return []
        text = zf.read(fn).decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))


def _shape_paths(src) -> dict[str, list[list[float]]]:
    """``shape_id -> [[lng, lat], …]`` ordered by ``shape_pt_sequence``."""
    rows = read_table(src, "shapes")
    by_shape: dict[str, list[tuple]] = {}
    for r in rows:
        sid = r.get("shape_id")
        if sid is None:
            continue
        try:
            seq = int(float(r["shape_pt_sequence"]))
            lat = float(r["shape_pt_lat"])
            lng = float(r["shape_pt_lon"])
        except (KeyError, TypeError, ValueError):
            continue
        by_shape.setdefault(sid, []).append((seq, lng, lat))
    return {sid: [[lng, lat] for _seq, lng, lat in sorted(pts)] for sid, pts in by_shape.items()}


def _stops_lookup(src) -> dict[str, list[float]]:
    """``stop_id -> [lng, lat]``."""
    out: dict[str, list[float]] = {}
    for r in read_table(src, "stops"):
        sid = r.get("stop_id")
        try:
            out[sid] = [float(r["stop_lon"]), float(r["stop_lat"])]
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _route_types(src) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in read_table(src, "routes"):
        try:
            out[r["route_id"]] = int(float(r.get("route_type", 3)))
        except (TypeError, ValueError):
            out[r["route_id"]] = 3
    return out


def _route_short_names(src) -> dict[str, str]:
    return {
        r["route_id"]: (r.get("route_short_name") or r.get("route_long_name") or r["route_id"])
        for r in read_table(src, "routes")
        if r.get("route_id")
    }


def route_lines(src, *, agency: str = "ttc") -> list[dict]:
    """Per-route geometry from ``shapes.txt`` (a representative shape per route).

    Falls back to the ordered stops of a representative trip when a feed has no
    shapes. Output matches ``routes.route_geometries`` (mode-tagged).
    """
    trips = read_table(src, "trips")
    shapes = _shape_paths(src)
    stops = _stops_lookup(src)
    rtypes = _route_types(src)
    shorts = _route_short_names(src)

    # First shape_id seen per route (deterministic via input order).
    route_shape: dict[str, str] = {}
    route_first_trip: dict[str, str] = {}
    for t in trips:
        rid = t.get("route_id")
        if rid is None:
            continue
        route_first_trip.setdefault(rid, t.get("trip_id"))
        sid = t.get("shape_id")
        if sid and rid not in route_shape:
            route_shape[rid] = sid

    stop_times_by_trip = _stop_times_by_trip(src)

    records: list[dict] = []
    for rid in sorted({t.get("route_id") for t in trips if t.get("route_id")}, key=str):
        path = shapes.get(route_shape.get(rid, ""))
        if not path:
            # Fall back to the representative trip's ordered stop coordinates.
            seq = stop_times_by_trip.get(route_first_trip.get(rid), [])
            path = [stops[s["stop_id"]] for s in seq if s.get("stop_id") in stops]
        if not path or len(path) < 2:
            continue
        records.append(
            {
                "route_id": rid,
                "route_short_name": shorts.get(rid, rid),
                "route_type": rtypes.get(rid, 3),
                "agency": agency,
                "path": path,
            }
        )
    return route_geometries(records)


def _stop_times_by_trip(src) -> dict[str, list[dict]]:
    """``trip_id -> [stop_time rows]`` ordered by ``stop_sequence``."""
    by_trip: dict[str, list[dict]] = {}
    for r in read_table(src, "stop_times"):
        tid = r.get("trip_id")
        if tid is None:
            continue
        by_trip.setdefault(tid, []).append(r)
    for tid, rows in by_trip.items():
        rows.sort(key=lambda r: int(float(r.get("stop_sequence", 0))))
    return by_trip


def trip_trajectories(src, *, agency: str = "ttc") -> list[dict]:
    """Per-trip ``{trip_id, route_id, route_type, agency, path, timestamps}``.

    Joins ``stop_times`` to ``stops`` for coordinates and reuses
    ``build_trajectory`` (monotonic seconds-since-midnight, no midnight wrap).
    """
    trips = read_table(src, "trips")
    stops = _stops_lookup(src)
    rtypes = _route_types(src)
    stop_times_by_trip = _stop_times_by_trip(src)

    out: list[dict] = []
    for t in trips:
        tid = t.get("trip_id")
        rid = t.get("route_id")
        rows = stop_times_by_trip.get(tid, [])
        stop_times = []
        for st in rows:
            coord = stops.get(st.get("stop_id"))
            if coord is None or st.get("arrival_time") in (None, ""):
                continue
            stop_times.append(
                {
                    "stop_sequence": int(float(st["stop_sequence"])),
                    "arrival_time": st["arrival_time"],
                    "lng": coord[0],
                    "lat": coord[1],
                }
            )
        traj = build_trajectory(stop_times)
        if len(traj["path"]) < 2:
            continue
        out.append(
            {
                "trip_id": tid,
                "route_id": rid,
                "route_type": rtypes.get(rid, 3),
                "mode": ROUTE_TYPE_MODE.get(rtypes.get(rid, 3), "bus"),
                "agency": agency,
                **traj,
            }
        )
    return out


def build_feed(src, *, agency: str = "ttc") -> dict:
    """Read a GTFS feed into the cached overlay payload ``{routes, trajectories}``."""
    return {
        "agency": agency,
        "routes": route_lines(src, agency=agency),
        "trajectories": trip_trajectories(src, agency=agency),
    }


def cache_path(agency: str, date: str, data_dir: str) -> str:
    return os.path.join(data_dir, "transit", f"{agency}_{date}.json")


def build_feed_cache(src, *, agency: str, date: str, data_dir: str) -> str:
    """Read ``src`` and write ``data/transit/{agency}_{date}.json``; return path."""
    feed = build_feed(src, agency=agency)
    feed["date"] = date
    out = cache_path(agency, date, data_dir)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(feed, fh)
    return out


def load_cached_feed(agency: str, date: str, data_dir: str) -> dict | None:
    """Return the cached real feed for ``(agency, date)`` if present, else None.

    Falls back to any cached date for the agency so the overlay can serve a real
    feed even when the requested service date wasn't the one baked.
    """
    exact = cache_path(agency, date, data_dir)
    if os.path.exists(exact):
        with open(exact) as fh:
            return json.load(fh)
    transit_dir = os.path.join(data_dir, "transit")
    if os.path.isdir(transit_dir):
        cands = sorted(
            fn
            for fn in os.listdir(transit_dir)
            if fn.startswith(f"{agency}_") and fn.endswith(".json")
        )
        if cands:
            with open(os.path.join(transit_dir, cands[-1])) as fh:
                return json.load(fh)
    return None
