"""P14 Phase 5 — confounder enrichment & matched controls.

A closure window also overlaps weather, incidents, events, holidays — so we attach
those signals and a matched-control anchor to support a difference-in-differences
read of the closure effect, and flag rows a confounder plausibly explains
(``confounder_dominated``) so they can be excluded from the clean training subset.

This module implements the testable core — **weather** (nearest hourly join +
window aggregate), **incidents** (KSI on/near the site during the window), and
**matched controls** (sites far from any active intervention). Events / TTC delays /
holiday-school flags follow the same join pattern and wire to the real
``research/07`` sources later. See ``docs/specs/14-closure-dataset.md`` Phase 5.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .spatial import haversine_m

WEATHER_FIELDS = ["temp_c", "precip_mm", "snow", "visibility_km", "wind_kmh"]


def survey_weather(during: pd.DataFrame, weather: pd.DataFrame, *, tolerance_h: int = 2) -> pd.DataFrame:
    """Nearest-hour weather join onto each during-survey (within ``tolerance_h``)."""
    if during.empty:
        return during.assign(**{f: pd.Series(dtype="float64") for f in WEATHER_FIELDS})
    d = during.sort_values("dt")
    w = weather.sort_values("dt")
    return pd.merge_asof(
        d, w, on="dt", direction="nearest", tolerance=pd.Timedelta(hours=tolerance_h)
    )


def aggregate_weather(during_with_weather: pd.DataFrame) -> pd.DataFrame:
    """Per (ID, centreline_id): summarise the during-window weather."""
    if during_with_weather.empty:
        return pd.DataFrame(columns=["ID", "centreline_id", *WEATHER_FIELDS])
    return (
        during_with_weather.groupby(["ID", "centreline_id"])
        .agg(
            temp_c=("temp_c", "mean"),
            precip_mm=("precip_mm", "mean"),
            snow=("snow", "max"),
            visibility_km=("visibility_km", "min"),
            wind_kmh=("wind_kmh", "mean"),
        )
        .reset_index()
    )


def flag_nearby_incidents(
    labels: pd.DataFrame, incidents: pd.DataFrame, *, radius_m: float = 200.0
) -> pd.DataFrame:
    """Set ``incident_nearby`` when a KSI collision occurred on/near the site in-window.

    ``labels`` needs ``site_lat``/``site_lon``/``StartTime``/``EndTime``; ``incidents``
    needs ``lat``/``lon``/``date`` (tz-aware).
    """
    out = labels.copy()
    out["incident_nearby"] = 0
    if incidents.empty or labels.empty:
        return out
    for i, row in out.iterrows():
        in_win = (incidents["date"] >= row["StartTime"]) & (incidents["date"] < row["EndTime"])
        if not in_win.any():
            continue
        sub = incidents[in_win]
        d = haversine_m(
            sub["lat"].to_numpy(), sub["lon"].to_numpy(), row["site_lat"], row["site_lon"]
        )
        if np.any(d <= radius_m):
            out.at[i, "incident_nearby"] = 1
    return out


def select_matched_controls(
    restrictions: pd.DataFrame, sites: pd.DataFrame, *, radius_m: float = 500.0, n_controls: int = 3
) -> pd.DataFrame:
    """For each restriction, pick control sites **far from any active intervention**.

    A site is eligible if it's > ``radius_m`` from *every* restriction (so no closure
    contaminates the control). Deterministic: the eligible sites are taken in sorted
    ``centreline_id`` order. Returns rows ``(ID, control_centreline_id)``. (Matching on
    road-class/time context is a documented refinement.)
    """
    if restrictions.empty or sites.empty:
        return pd.DataFrame(columns=["ID", "control_centreline_id"])
    # min distance from each site to ANY restriction
    site_lat = sites["site_lat"].to_numpy()
    site_lon = sites["site_lon"].to_numpy()
    min_dist = np.full(len(sites), np.inf)
    for _, r in restrictions.iterrows():
        d = haversine_m(site_lat, site_lon, r["Latitude"], r["Longitude"])
        min_dist = np.minimum(min_dist, d)
    eligible = sorted(sites.loc[min_dist > radius_m, "centreline_id"].tolist())[:n_controls]

    rows = [
        {"ID": rid, "control_centreline_id": cid}
        for rid in restrictions["ID"].tolist()
        for cid in eligible
    ]
    return pd.DataFrame(rows, columns=["ID", "control_centreline_id"])


def mark_confounder_dominated(labels: pd.DataFrame) -> pd.DataFrame:
    """Flag rows a confounder plausibly explains (currently: an in-window on-link KSI)."""
    out = labels.copy()
    flag = out["incident_nearby"] if "incident_nearby" in out.columns else 0
    out["confounder_dominated"] = (
        pd.Series(flag, index=out.index).fillna(0).astype(int) > 0
    ).astype("int8")
    return out
