"""Open-Meteo historical hourly weather for closure windows (P13 enrichment).

The P14 confounder join (``groundtruth.confounders.survey_weather``) wants a weather
frame in the ``WEATHER_FIELDS`` schema (``dt`` + ``temp_c/precip_mm/snow/visibility_km/
wind_kmh``). The repo's 2020 ECCC files don't cover the real closures (2024–2026) and no
raw→schema loader exists, so we pull the matching window from **Open-Meteo's free, keyless
historical archive** (hourly, UTC, global) directly in that schema. The HTTP call runs
where the pipeline runs (the GB10); ``_parse_openmeteo`` is network-free and unit-tested.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

import pandas as pd

# Toronto City Hall — the closures + TMC sites cluster around the core
TORONTO_LATLON = (43.6532, -79.3832)
_HOURLY = "temperature_2m,precipitation,snowfall,wind_speed_10m,visibility"


def _parse_openmeteo(data: dict) -> pd.DataFrame:
    """Open-Meteo JSON → the ``WEATHER_FIELDS`` frame (``dt`` UTC + the 5 fields)."""
    h = data["hourly"]

    def _km(v):
        return v / 1000.0 if v is not None else float("nan")  # metres → km

    return pd.DataFrame(
        {
            "dt": pd.to_datetime(h["time"], utc=True),
            "temp_c": h["temperature_2m"],
            "precip_mm": h["precipitation"],
            "snow": h["snowfall"],  # cm of snowfall in the hour
            "wind_kmh": h["wind_speed_10m"],
            "visibility_km": [_km(v) for v in h["visibility"]],
        }
    )


def fetch_weather_openmeteo(  # pragma: no cover - network call (GB10)
    start_date,
    end_date,
    *,
    lat: float = TORONTO_LATLON[0],
    lon: float = TORONTO_LATLON[1],
    timeout: int = 90,
) -> pd.DataFrame:
    """Hourly Toronto weather over ``[start_date, end_date]`` (``YYYY-MM-DD``) as a frame."""
    q = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "hourly": _HOURLY,
            "timezone": "UTC",
            "wind_speed_unit": "kmh",
        }
    )
    url = f"https://archive-api.open-meteo.com/v1/archive?{q}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return _parse_openmeteo(json.load(resp))


def weather_label(*, snow=None, precip_mm=None) -> str:
    """Coarse condition string for the context channel (``snow``/``rain``/``clear``)."""
    if snow is not None and snow == snow and float(snow) > 0:
        return "snow"
    if precip_mm is not None and precip_mm == precip_mm and float(precip_mm) >= 0.2:
        return "rain"
    return "clear"
