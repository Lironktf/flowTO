#!/usr/bin/env python3
"""LOCATION: torontosim/model/ingest_real_data.py  (load_tmc + build_dataset)

The heaviest pandas workload in the repo: read & concat the raw TMC CSVs,
coerce the 36 vehicle-movement columns to numeric, sum into a 15-min total,
parse start_time, derive time parts, drop bad rows, then group to an hourly
volume per (intersection, date, hour). Operations copied from load_tmc() and
the groupby in build_dataset().
"""
from __future__ import annotations

import glob
import os

from _harness import finalize, main, stage

# --- copied from torontosim/model/ingest_real_data.py ----------------------
_APPR = ["n", "s", "e", "w"]
_VEH = ["cars", "truck", "bus"]
_TURNS = ["r", "t", "l"]
VEHICLE_COLS = [f"{a}_appr_{v}_{t}" for a in _APPR for v in _VEH for t in _TURNS]
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(_REPO_ROOT, "data", "raw")
GROUP_KEYS = ["loc_id", "year", "month", "day", "hour", "day_of_week", "is_weekend"]


def pipeline(xp, sync):
    t = {}
    files = sorted(glob.glob(os.path.join(RAW_DIR, "tmc_raw_data_*.csv")))

    with stage(t, "read_csv", sync):
        frames = [xp.read_csv(f) for f in files]
    with stage(t, "concat", sync):
        df = xp.concat(frames, ignore_index=True)
    n_in = len(df)

    present = [c for c in VEHICLE_COLS if c in df.columns]
    with stage(t, "to_numeric+fillna", sync):
        for c in present:
            df[c] = xp.to_numeric(df[c], errors="coerce").fillna(0)
    with stage(t, "rowsum(veh_15min)", sync):
        df["veh_15min"] = df[present].sum(axis=1)

    with stage(t, "to_datetime", sync):
        # data is uniformly ISO-formatted; explicit format works on both
        # backends (cuDF's to_datetime has no errors="coerce" for arrays).
        df["ts"] = xp.to_datetime(df["start_time"], format="%Y-%m-%dT%H:%M:%S")
    with stage(t, "datetime_parts", sync):
        df["loc_id"] = df["centreline_id"]
        df["lat"] = xp.to_numeric(df["latitude"], errors="coerce")
        df["lon"] = xp.to_numeric(df["longitude"], errors="coerce")
        df["year"] = df["ts"].dt.year
        df["month"] = df["ts"].dt.month
        df["day"] = df["ts"].dt.day
        df["hour"] = df["ts"].dt.hour
        df["day_of_week"] = df["ts"].dt.dayofweek
        df["is_weekend"] = (df["day_of_week"] >= 5).astype("int32")
    with stage(t, "dropna", sync):
        df = df.dropna(subset=["loc_id", "lat", "lon", "ts"])

    with stage(t, "groupby_agg", sync):
        grp = (
            df.groupby(GROUP_KEYS, as_index=False)
            .agg({"veh_15min": "sum", "lat": "first", "lon": "first"})
            .rename(columns={"veh_15min": "vehicle_count"})
        )
    return finalize(t), f"{n_in:,} rows -> {len(grp):,} hourly records"


TITLE = "ingest_real_data.py : load_tmc + hourly groupby (raw TMC CSVs)"

if __name__ == "__main__":
    main(TITLE, pipeline)
