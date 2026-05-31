"""P14 Phase 2 — temporal split & "during" aggregation.

Compute per-TMC-row volumes by vehicle class (cars/trucks/buses + peds/bikes) and
approach direction (n/s/e/w), then, for each (restriction × neighbour site) pair,
summarise the traffic recorded **while the restriction was active**
(``StartTime ≤ dt < EndTime``, half-open). A site with no in-window survey produces
**no** during row (honesty — not a zero row).

See ``docs/specs/14-closure-dataset.md`` Phase 2.
"""

from __future__ import annotations

import pandas as pd

CARS = [f"{d}_appr_cars_{m}" for d in "nsew" for m in "rtl"]
TRUCK = [f"{d}_appr_truck_{m}" for d in "nsew" for m in "rtl"]
BUS = [f"{d}_appr_bus_{m}" for d in "nsew" for m in "rtl"]
PEDS = [f"{d}_appr_peds" for d in "nsew"]
BIKE = [f"{d}_appr_bike" for d in "nsew"]
VEH = CARS + TRUCK + BUS


def tmc_observations(tmc: pd.DataFrame) -> pd.DataFrame:
    """Raw TMC rows → tidy per-survey observations with class/direction totals.

    Parses ``start_time`` (ISO, treated as UTC for comparability with the epoch-ms
    restriction windows) and sums the movement columns present in the frame.
    """
    t = tmc.copy()
    t["dt"] = pd.to_datetime(t["start_time"], format="%Y-%m-%dT%H:%M:%S").dt.tz_localize("UTC")
    t["hour"] = t["dt"].dt.hour.astype("int16")
    t["dow"] = t["dt"].dt.dayofweek.astype("int16")

    present = [c for c in CARS + TRUCK + BUS + PEDS + BIKE if c in t.columns]
    t[present] = t[present].fillna(0)

    def _sum(cols):
        cols = [c for c in cols if c in t.columns]
        return t[cols].sum(axis=1) if cols else 0

    t["cars"] = _sum(CARS)
    t["trucks"] = _sum(TRUCK)
    t["buses"] = _sum(BUS)
    t["peds"] = _sum(PEDS)
    t["bikes"] = _sum(BIKE)
    t["vol"] = _sum(VEH)
    for d in "nsew":
        t[f"dir_{d}"] = _sum([c for c in VEH if c.startswith(f"{d}_appr")])

    keep = [
        "centreline_id", "count_id", "dt", "hour", "dow", "vol",
        "cars", "trucks", "buses", "peds", "bikes",
        "dir_n", "dir_s", "dir_e", "dir_w",
    ]
    return t[keep]


def split_during_pre(pairs: pd.DataFrame, obs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-survey rows split into during-window and pre-window (same site).

    ``during`` = ``StartTime ≤ dt < EndTime`` (half-open); ``pre`` = ``dt < StartTime``.
    Both carry the per-survey class/direction columns so Phase 3 can build a baseline.
    """
    cand = pairs[["ID", "centreline_id", "StartTime", "EndTime"]].merge(
        obs, on="centreline_id", how="inner"
    )
    during = cand[(cand["dt"] >= cand["StartTime"]) & (cand["dt"] < cand["EndTime"])]
    pre = cand[cand["dt"] < cand["StartTime"]]
    return during, pre


def during_aggregate(pairs: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    """Per (ID, centreline_id): summarise surveys inside the restriction window."""
    during, _ = split_during_pre(pairs, obs)
    if during.empty:
        return pd.DataFrame(columns=["ID", "centreline_id", "obs_during"])
    return (
        during.groupby(["ID", "centreline_id"])
        .agg(
            obs_during=("vol", "count"),
            survey_days_during=("count_id", "nunique"),
            during_vol_mean=("vol", "mean"),
            during_vol_sum=("vol", "sum"),
            during_cars=("cars", "mean"),
            during_trucks=("trucks", "mean"),
            during_buses=("buses", "mean"),
            during_peds=("peds", "mean"),
            during_bikes=("bikes", "mean"),
            during_dir_n=("dir_n", "mean"),
            during_dir_s=("dir_s", "mean"),
            during_dir_e=("dir_e", "mean"),
            during_dir_w=("dir_w", "mean"),
        )
        .reset_index()
    )
