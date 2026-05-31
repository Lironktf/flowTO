"""P14 Phase 4 — openings (reopening / added capacity).

A restriction's ``EndTime`` is a **reopening event**. The "after" window is
``[EndTime, EndTime + min(duration, cap_days))``; the opening label compares the
after-reopening traffic to the **during-closure** traffic at the same site (the
recovery signal), reusing the Phase-3 baseline + signed-label machinery with
``intervention_sign='opening'``.

Honest: an opening row needs a survey *after* reopening at the same site → expect
**far fewer** rows than closures (most ``EndTime``s are future-dated). Report the
realized count; never pad it.

See ``docs/specs/14-closure-dataset.md`` Phase 4.
"""

from __future__ import annotations

import pandas as pd

from .labels import apply_signed_labels, build_baseline


def split_after(pairs: pd.DataFrame, obs: pd.DataFrame, *, cap_days: float = 90.0) -> pd.DataFrame:
    """Per-survey rows in the after-reopening window ``[EndTime, EndTime+min(dur,cap))``."""
    cand = pairs[["ID", "centreline_id", "StartTime", "EndTime"]].merge(
        obs, on="centreline_id", how="inner"
    )
    dur_days = (cand["EndTime"] - cand["StartTime"]).dt.total_seconds() / 86400.0
    win_days = dur_days.clip(upper=cap_days)
    after_end = cand["EndTime"] + pd.to_timedelta(win_days, unit="D")
    return cand[(cand["dt"] >= cand["EndTime"]) & (cand["dt"] < after_end)]


def after_aggregate(after: pd.DataFrame) -> pd.DataFrame:
    """Per (ID, centreline_id): summarise the after-reopening surveys."""
    if after.empty:
        return pd.DataFrame(columns=["ID", "centreline_id", "after_vol_mean"])
    return (
        after.groupby(["ID", "centreline_id"])
        .agg(
            after_obs=("vol", "count"),
            after_survey_days=("count_id", "nunique"),
            after_vol_mean=("vol", "mean"),
            after_cars=("cars", "mean"),
            after_trucks=("trucks", "mean"),
            after_buses=("buses", "mean"),
        )
        .reset_index()
    )


def build_opening_labels(
    after_agg: pd.DataFrame, after: pd.DataFrame, during: pd.DataFrame
) -> pd.DataFrame:
    """Opening labels: after-reopening vs during-closure baseline at the same site."""
    base = build_baseline(after, during)  # slots from after, baseline drawn from during
    ds = after_agg.merge(base, on=["ID", "centreline_id"], how="left")
    return apply_signed_labels(ds, "after_vol_mean", "opening")
