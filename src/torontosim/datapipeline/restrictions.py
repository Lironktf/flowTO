"""Road restrictions / closures — the live CART feed (research/01 §5).

Endpoint (live, not a datastore copy):
    https://secure.toronto.ca/opendata/cart/road_restrictions/v3?format=json

Gotchas handled here: needs a browser ``User-Agent`` (else 403/404); times are
**epoch milliseconds**; ``geoPolyline`` is a list of ``[lng, lat]`` pairs (not
GeoJSON). Restrictions are a *demo input* (closures to simulate), not load-
bearing — snapshot once if the feed is flaky.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FEED_URL = "https://secure.toronto.ca/opendata/cart/road_restrictions/v3?format=json"
_UA = {"User-Agent": "Mozilla/5.0 (TorontoSim road-restrictions)"}


def _epoch_ms_to_dt(value: Any) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _polyline_to_linestring(poly: Any):
    """``[[lng,lat], ...]`` (or a "lat,lng lat,lng" string) -> shapely LineString."""
    from shapely.geometry import LineString

    coords: list[tuple[float, float]] = []
    if isinstance(poly, str):
        # Fallback: space-separated "lat,lng" pairs.
        for pair in poly.split():
            parts = pair.split(",")
            if len(parts) == 2:
                lat, lng = float(parts[0]), float(parts[1])
                coords.append((lng, lat))
    elif isinstance(poly, list):
        for pt in poly:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                lng, lat = float(pt[0]), float(pt[1])
                coords.append((lng, lat))
    if len(coords) < 2:
        return None
    return LineString(coords)


def _records(payload: Any) -> list[dict]:
    """Pull the list of closures from the feed (dict-wrapped or bare list)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        # CART wraps closures under a key (e.g. "Closure"); take the first list.
        for value in payload.values():
            if isinstance(value, list):
                return value
    return []


def parse(payload: Any) -> list[dict]:
    """Normalize the CART payload into typed restriction records.

    Each record: id, road, name, road_class, planned (bool), type,
    directions_affected, max_impact, start_time/end_time (aware datetime or
    None), and geometry (shapely LineString or None).
    """
    out: list[dict] = []
    for rec in _records(payload):
        planned_raw = rec.get("planned")
        planned = str(planned_raw).strip().lower() in ("1", "true", "yes")
        out.append(
            {
                "id": rec.get("id"),
                "road": rec.get("road"),
                "name": rec.get("name"),
                "road_class": rec.get("roadClass"),
                "planned": planned,
                "type": rec.get("type"),
                "directions_affected": rec.get("directionsAffected"),
                "max_impact": rec.get("maxImpact"),
                "start_time": _epoch_ms_to_dt(rec.get("startTime")),
                "end_time": _epoch_ms_to_dt(rec.get("endTime")),
                "geometry": _polyline_to_linestring(rec.get("geoPolyline")),
            }
        )
    return out


def fetch(*, session=None, timeout: int = 60) -> list[dict]:
    """Fetch + parse the live feed (browser UA). Network — call before demo."""
    import requests

    sess = session or requests.Session()
    r = sess.get(FEED_URL, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return parse(r.json())
