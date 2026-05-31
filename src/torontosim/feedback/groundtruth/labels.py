"""P14 Phase 3 — pre-intervention baseline & signed labels.

For each (restriction × neighbour site) we compare the during-window traffic to a
**pre-intervention baseline at the same site**, matched on time-of-day so we compare
like with like:
  * Tier 1 — match on (hour, dow): the most like-for-like baseline.
  * Tier 2 — fall back to (hour) only where Tier 1 is empty (sparse surveys often
    miss the exact weekday). ``baseline_match`` records which tier was used.

The label is **signed**: a closure usually *lowers* volume on the segment and *raises*
it on detours — never assume "closure ⇒ more traffic". Rows with no pre-survey get
``has_baseline=0`` and null deltas (no fabrication).

See ``docs/specs/14-closure-dataset.md`` Phase 3.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SIG_SIGMA = 1.5  # |Δ in baseline std-devs| above which an impact is "significant"


def _baseline_agg(matched: pd.DataFrame) -> pd.DataFrame:
    return (
        matched.groupby(["ID", "centreline_id"])
        .agg(
            base_n=("vol", "count"),
            base_survey_days=("count_id", "nunique"),
            base_vol_mean=("vol", "mean"),
            base_vol_std=("vol", "std"),
            base_cars=("cars", "mean"),
            base_trucks=("trucks", "mean"),
            base_buses=("buses", "mean"),
        )
        .reset_index()
    )


def build_baseline(during: pd.DataFrame, pre: pd.DataFrame) -> pd.DataFrame:
    """Tier-1 (hour,dow) baseline, falling back to Tier-2 (hour) where Tier-1 is empty."""
    slots_hd = during[["ID", "centreline_id", "hour", "dow"]].drop_duplicates()
    base_hd = _baseline_agg(
        pre.merge(slots_hd, on=["ID", "centreline_id", "hour", "dow"], how="inner")
    )
    base_hd["baseline_match"] = "hour_dow"

    slots_h = during[["ID", "centreline_id", "hour"]].drop_duplicates()
    base_h = _baseline_agg(pre.merge(slots_h, on=["ID", "centreline_id", "hour"], how="inner"))
    base_h["baseline_match"] = "hour"

    # prefer the (hour,dow) baseline; use (hour) only where Tier-1 is missing
    have_hd = base_hd[["ID", "centreline_id"]].assign(_hd=1)
    base_h = base_h.merge(have_hd, on=["ID", "centreline_id"], how="left")
    base_h = base_h[base_h["_hd"].isna()].drop(columns="_hd")
    return pd.concat([base_hd, base_h], ignore_index=True)


def build_labels(
    during_agg: pd.DataFrame, during: pd.DataFrame, pre: pd.DataFrame
) -> pd.DataFrame:
    """Join the baseline onto the during-aggregate and compute the signed labels."""
    base = build_baseline(during, pre)
    ds = during_agg.merge(base, on=["ID", "centreline_id"], how="left")

    ds["has_baseline"] = ds["base_n"].notna().astype("int8")
    ds["baseline_match"] = ds["baseline_match"].fillna("none")
    ds["vol_delta"] = ds["during_vol_mean"] - ds["base_vol_mean"]
    ds["vol_delta_pct"] = (
        ds["vol_delta"] / ds["base_vol_mean"].where(ds["base_vol_mean"] != 0) * 100.0
    )
    ds["vol_sigma"] = ds["vol_delta"] / ds["base_vol_std"].where(ds["base_vol_std"] > 0)

    no_base = ds["has_baseline"] == 0
    ds["direction"] = pd.array(np.where(ds["vol_delta"] >= 0, 1, 0), dtype="Int8")
    ds["significant"] = pd.array(
        np.where(ds["vol_sigma"].abs() > SIG_SIGMA, 1, 0), dtype="Int8"
    )
    # no baseline → labels are undefined, not 0 (honesty)
    ds.loc[no_base, ["direction", "significant"]] = pd.NA
    return ds
