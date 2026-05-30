"""ECCC hourly weather ingest + filename normalization (research/01).

Liron's ``fetch_data.sh`` writes ``weather_YYYY_MM.csv`` from the ECCC bulk
endpoint (Toronto Pearson, station 51459). A few legacy files were malformed
(``weather_2023 6_00.csv`` — a space and a trailing ``_00``). This module
canonicalizes those names and maps hourly rows to a coarse weather *category*
that the demand model consumes.
"""

from __future__ import annotations

import os
import re

# Categories the demand model understands (see model.features.weather_speed_factor).
CATEGORIES = ("clear", "rain", "snow", "fog", "storm")

# Accepts: weather_2020_01.csv, weather_2023 6_00.csv, weather_2023_6.csv …
_FN_RE = re.compile(r"weather[_ ]+(\d{4})[_ ]+(\d{1,2})", re.IGNORECASE)


def parse_filename(name: str) -> tuple[int, int]:
    """Extract ``(year, month)`` from a (possibly malformed) weather filename."""
    base = os.path.basename(name)
    m = _FN_RE.search(base)
    if not m:
        raise ValueError(f"unrecognized weather filename: {name!r}")
    return int(m.group(1)), int(m.group(2))


def canonical_name(year: int, month: int) -> str:
    """The canonical ``weather_YYYY_MM.csv`` filename."""
    return f"weather_{year:04d}_{month:02d}.csv"


def fix_filenames(weather_dir: str) -> list[tuple[str, str]]:
    """Rename malformed files in ``weather_dir`` to canonical form.

    Returns the list of ``(old, new)`` renames actually performed.
    """
    renames: list[tuple[str, str]] = []
    if not os.path.isdir(weather_dir):
        return renames
    for fn in os.listdir(weather_dir):
        if not fn.lower().startswith("weather"):
            continue
        try:
            y, mo = parse_filename(fn)
        except ValueError:
            continue
        canon = canonical_name(y, mo)
        if fn != canon:
            src = os.path.join(weather_dir, fn)
            dst = os.path.join(weather_dir, canon)
            if not os.path.exists(dst):
                os.rename(src, dst)
                renames.append((fn, canon))
    return renames


def categorize(weather_text: str | None, temp_c: float | None = None) -> str:
    """Map an ECCC "Weather" string (+ temp) to one of ``CATEGORIES``."""
    t = (weather_text or "").lower()
    if any(w in t for w in ("thunder", "storm", "squall")):
        return "storm"
    if any(w in t for w in ("snow", "ice", "sleet", "freezing")):
        return "snow"
    if any(w in t for w in ("rain", "drizzle", "shower")):
        return "rain"
    if any(w in t for w in ("fog", "mist", "haze")):
        return "fog"
    if temp_c is not None and temp_c <= -2.0:
        # Cold + (often) blank weather string in winter rows -> treat as snow risk.
        return "snow"
    return "clear"
