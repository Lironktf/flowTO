"""P14 Phase 0 — clean_restrictions tests (CPU pandas; runs on the GB10)."""

from __future__ import annotations

import csv

import pandas as pd

from torontosim.feedback.groundtruth.clean import KEEP, clean_restrictions

# header = the KEEP columns + a couple of trailing columns like the real feed
HEADER = KEEP + ["Notification", "PermitType"]


def _row(**over):
    base = {
        "ID": "1001",
        "Road": "Collier St",
        "Name": "Collier St work",
        "District": "TORONTO",
        "RoadClass": "Local Road",
        "Planned": "1",
        "Latitude": "43.6725",
        "Longitude": "-79.3849",
        "StartTime": "1743075202000",  # ~2025-03-27 (epoch ms)
        "EndTime": "1893456000000",  # ~2030 (epoch ms)
        "MaxImpact": "Low",
        "CurrImpact": "Low",
        "Type": "CONSTRUCTION",
        "SubType": "",
        "DirectionsAffected": "ONE_DIRECTION",
        "WorkEventType": "",
        "Signing": "",
        "Notification": "",
        "PermitType": "",
    }
    base.update(over)
    return [base[c] for c in HEADER]


def _write_v3(tmp_path, data_rows):
    p = tmp_path / "v3.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Current road restrictions"])  # title banner
        w.writerow(HEADER)
        for r in data_rows:
            w.writerow(r)
    return p


def test_drops_banner_and_keeps_valid(tmp_path):
    p = _write_v3(tmp_path, [_row(ID="1"), _row(ID="2")])
    df = clean_restrictions(p)
    assert len(df) == 2
    assert df.attrs["dropped"] == 0
    assert list(df["ID"]) == ["1", "2"]
    assert list(df.columns)[: len(KEEP)] == KEEP  # banner/header handled, KEEP order


def test_drops_misaligned_and_unparseable(tmp_path):
    good = _row(ID="ok")
    short = ["only", "three", "fields"]  # misaligned → drop
    bad_time = _row(ID="badtime", StartTime="not-a-number")  # unparseable → drop
    bad_latlon = _row(ID="badll", Latitude="xx")  # unparseable → drop
    p = _write_v3(tmp_path, [good, short, bad_time, bad_latlon])
    df = clean_restrictions(p)
    assert list(df["ID"]) == ["ok"]
    assert df.attrs["dropped"] == 3


def test_types_and_duration(tmp_path):
    p = _write_v3(tmp_path, [_row(ID="1")])
    df = clean_restrictions(p)
    row = df.iloc[0]
    assert pd.api.types.is_datetime64_any_dtype(df["StartTime"])
    assert df["Latitude"].dtype == float and df["Planned"].dtype.kind in "iu"
    # 1893456000000 - 1743075202000 ms ≈ 1740.5 days
    assert 1700 < row["duration_days"] < 1800
    assert row["StartTime"].year == 2025


def test_missing_required_column_raises(tmp_path):
    p = tmp_path / "bad.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["banner"])
        w.writerow(["ID", "Road"])  # missing most KEEP columns
        w.writerow(["1", "x"])
    try:
        clean_restrictions(p)
    except KeyError as e:
        assert "Latitude" in str(e) or "StartTime" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError for missing columns")
