"""P14 Phase 1 — spatial join (intervention × TMC site within a radius).

A "site" is a physical intersection keyed by ``centreline_id`` (surveyed on many
days), NOT a ``count_id`` (a single survey day) — that distinction is what later
lets us build a before/during baseline (Phase 3). We join each restriction to every
TMC site within ``radius_m`` metres, recording the haversine distance + compass
bearing closure→site. A cheap bounding-box prefilter runs before the haversine.

See ``docs/specs/14-closure-dataset.md`` Phase 1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_M = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Great-circle distance in metres (vectorized)."""
    la1, lo1, la2, lo2 = (
        np.radians(np.asarray(z, dtype=np.float64)) for z in (lat1, lon1, lat2, lon2)
    )
    dlat, dlon = la2 - la1, lo2 - lo1
    a = np.sin(dlat / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(dlon / 2) ** 2
    return EARTH_M * 2 * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Initial compass bearing 1→2 in degrees (0=N, 90=E), vectorized."""
    la1, lo1, la2, lo2 = (
        np.radians(np.asarray(z, dtype=np.float64)) for z in (lat1, lon1, lat2, lon2)
    )
    dlon = lo2 - lo1
    y = np.sin(dlon) * np.cos(la2)
    x = np.cos(la1) * np.sin(la2) - np.sin(la1) * np.cos(la2) * np.cos(dlon)
    return (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0


def tmc_sites(tmc: pd.DataFrame) -> pd.DataFrame:
    """Collapse raw TMC rows to physical sites: centreline_id → mean lat/lon + name."""
    sites = (
        tmc.groupby("centreline_id")
        .agg(site_lat=("latitude", "mean"), site_lon=("longitude", "mean"))
        .reset_index()
    )
    names = tmc[["centreline_id", "location_name"]].drop_duplicates("centreline_id")
    return sites.merge(names, on="centreline_id")


def spatial_join(
    sites: pd.DataFrame,
    restrictions: pd.DataFrame,
    *,
    radius_m: float = 500.0,
    box_deg: float = 0.006,
) -> pd.DataFrame:
    """Return (restriction ID × neighbour site) pairs within ``radius_m``.

    Each row carries the site key (``centreline_id``), site + closure coordinates,
    ``dist_m`` (haversine), ``bearing_deg``, the restriction attributes, and
    ``n_neighbour_sites`` (how many sites the restriction has in the set).
    """
    s, r = sites.copy(), restrictions.copy()
    s["_k"], r["_k"] = 1, 1
    pairs = s.merge(r, on="_k").drop(columns="_k")
    # cheap bounding-box prefilter (superset of the radius), then exact haversine
    pairs = pairs[
        ((pairs["site_lat"] - pairs["Latitude"]).abs() <= box_deg)
        & ((pairs["site_lon"] - pairs["Longitude"]).abs() <= box_deg)
    ].reset_index(drop=True)

    cols = ["centreline_id", "location_name", "site_lat", "site_lon", "dist_m", "bearing_deg"]
    if pairs.empty:
        return pairs.reindex(
            columns=list(pairs.columns) + ["dist_m", "bearing_deg", "n_neighbour_sites"]
        )

    pairs["dist_m"] = haversine_m(
        pairs["Latitude"].to_numpy(),
        pairs["Longitude"].to_numpy(),
        pairs["site_lat"].to_numpy(),
        pairs["site_lon"].to_numpy(),
    )
    pairs["bearing_deg"] = bearing_deg(
        pairs["Latitude"].to_numpy(),
        pairs["Longitude"].to_numpy(),
        pairs["site_lat"].to_numpy(),
        pairs["site_lon"].to_numpy(),
    )
    pairs = pairs[pairs["dist_m"] <= radius_m].reset_index(drop=True)
    pairs = pairs.rename(
        columns={
            "Latitude": "closure_lat",
            "Longitude": "closure_lon",
            "Road": "closure_road",
            "Name": "closure_name",
        }
    )
    if not pairs.empty:
        pairs["n_neighbour_sites"] = pairs.groupby("ID")["centreline_id"].transform("count")
    else:
        pairs["n_neighbour_sites"] = pd.Series(dtype="int64")
    _ = cols  # documented output columns (present alongside the restriction attrs)
    return pairs
