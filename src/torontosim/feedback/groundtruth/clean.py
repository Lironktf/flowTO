"""P14 Phase 0 — clean the CART road-restrictions snapshot.

``v3.csv`` (a pull of the live CART road-restrictions feed) has two problems a
DataFrame reader can't handle directly:
  1. a title-banner row ("Current road restrictions") above the real header;
  2. some rows with unescaped quotes/commas inside embedded-JSON columns
     (Signing / Notification / PermitType) that break field alignment.

We read with the stdlib ``csv`` reader (which the well-formed rows parse correctly),
keep only the columns we need, drop the misaligned rows, and return a typed pandas
DataFrame. ``StartTime``/``EndTime`` are **epoch-milliseconds** in the feed → parsed
to UTC datetimes here (the v1 cuDF stage deferred this; we do it up front).

See ``docs/specs/14-closure-dataset.md`` Phase 0.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

KEEP = [
    "ID", "Road", "Name", "District", "RoadClass", "Planned",
    "Latitude", "Longitude", "StartTime", "EndTime",
    "MaxImpact", "CurrImpact", "Type", "SubType",
    "DirectionsAffected", "WorkEventType", "Signing",
]


def clean_restrictions(v3_path: str | Path) -> pd.DataFrame:
    """Read a CART ``v3.csv`` snapshot → cleaned, typed restrictions DataFrame.

    Drops the title banner, misaligned rows (fewer fields than the header), and rows
    whose ``StartTime``/``EndTime`` (epoch ms) or ``Latitude``/``Longitude`` don't
    parse. The number dropped is recorded in ``df.attrs['dropped']``.
    """
    with open(v3_path, newline="") as fh:
        rows = list(csv.reader(fh))
    if len(rows) < 2:
        raise ValueError(f"{v3_path}: expected a title row + header, got {len(rows)} rows")

    header = rows[1]  # row 0 is the title banner
    ix = {h: i for i, h in enumerate(header)}
    missing = [c for c in KEEP if c not in ix]
    if missing:
        raise KeyError(f"{v3_path}: header missing required columns {missing}")

    records: list[dict] = []
    dropped = 0
    for r in rows[2:]:
        if len(r) < len(header):  # truncated / misaligned → drop
            dropped += 1
            continue
        try:
            int(r[ix["StartTime"]])
            int(r[ix["EndTime"]])
            float(r[ix["Latitude"]])
            float(r[ix["Longitude"]])
        except (ValueError, IndexError):
            dropped += 1
            continue
        records.append({k: r[ix[k]] for k in KEEP})

    df = pd.DataFrame.from_records(records, columns=KEEP)
    if not df.empty:
        df["StartTime"] = pd.to_datetime(df["StartTime"].astype("int64"), unit="ms", utc=True)
        df["EndTime"] = pd.to_datetime(df["EndTime"].astype("int64"), unit="ms", utc=True)
        df["Latitude"] = df["Latitude"].astype(float)
        df["Longitude"] = df["Longitude"].astype(float)
        df["Planned"] = pd.to_numeric(df["Planned"], errors="coerce").fillna(0).astype(int)
        df["duration_days"] = (df["EndTime"] - df["StartTime"]).dt.total_seconds() / 86400.0
    df.attrs["dropped"] = dropped
    return df
