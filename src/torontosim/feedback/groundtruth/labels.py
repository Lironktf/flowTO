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


def build_baseline(target_surveys: pd.DataFrame, baseline_surveys: pd.DataFrame) -> pd.DataFrame:
    """Tier-1 (hour,dow) baseline, falling back to Tier-2 (hour) where Tier-1 is empty.

    The baseline is drawn from ``baseline_surveys`` at the time-of-day slots observed
    in ``target_surveys`` (same site). Closures: target=during, baseline=pre. Openings:
    target=after, baseline=during (Phase 4).
    """
    slots_hd = target_surveys[["ID", "centreline_id", "hour", "dow"]].drop_duplicates()
    base_hd = _baseline_agg(
        baseline_surveys.merge(slots_hd, on=["ID", "centreline_id", "hour", "dow"], how="inner")
    )
    base_hd["baseline_match"] = "hour_dow"

    slots_h = target_surveys[["ID", "centreline_id", "hour"]].drop_duplicates()
    base_h = _baseline_agg(
        baseline_surveys.merge(slots_h, on=["ID", "centreline_id", "hour"], how="inner")
    )
    base_h["baseline_match"] = "hour"

    # prefer the (hour,dow) baseline; use (hour) only where Tier-1 is missing
    have_hd = base_hd[["ID", "centreline_id"]].assign(_hd=1)
    base_h = base_h.merge(have_hd, on=["ID", "centreline_id"], how="left")
    base_h = base_h[base_h["_hd"].isna()].drop(columns="_hd")
    return pd.concat([base_hd, base_h], ignore_index=True)


def apply_signed_labels(ds: pd.DataFrame, target_mean_col: str, sign: str) -> pd.DataFrame:
    """Compute signed delta labels from a target-vs-baseline merged frame.

    Shared by closures (target = during, ``sign='closure'``) and openings (target =
    after, ``sign='opening'``). ``ds`` must carry ``base_vol_mean``/``base_vol_std``/
    ``base_n`` (from ``build_baseline``) and ``target_mean_col``. No baseline → null
    deltas (not 0).
    """
    ds = ds.copy()
    ds["intervention_sign"] = sign
    ds["has_baseline"] = ds["base_n"].notna().astype("int8")
    ds["baseline_match"] = ds["baseline_match"].fillna("none")
    ds["vol_delta"] = ds[target_mean_col] - ds["base_vol_mean"]
    ds["vol_delta_pct"] = (
        ds["vol_delta"] / ds["base_vol_mean"].where(ds["base_vol_mean"] != 0) * 100.0
    )
    ds["vol_sigma"] = ds["vol_delta"] / ds["base_vol_std"].where(ds["base_vol_std"] > 0)

    no_base = ds["has_baseline"] == 0
    ds["direction"] = pd.array(np.where(ds["vol_delta"] >= 0, 1, 0), dtype="Int8")
    ds["significant"] = pd.array(
        np.where(ds["vol_sigma"].abs() > SIG_SIGMA, 1, 0), dtype="Int8"
    )
    ds.loc[no_base, ["direction", "significant"]] = pd.NA  # honesty: undefined, not 0
    return ds


def build_labels(
    during_agg: pd.DataFrame, during: pd.DataFrame, pre: pd.DataFrame
) -> pd.DataFrame:
    """Closure labels: during-window vs pre-intervention baseline at the same site."""
    base = build_baseline(during, pre)
    ds = during_agg.merge(base, on=["ID", "centreline_id"], how="left")
    return apply_signed_labels(ds, "during_vol_mean", "closure")
