#!/usr/bin/env python3
"""LOCATION: torontosim/model/odme_calibrate.py  (fetch_observed_counts)

Builds per-node observed mean counts for OD-matrix calibration: read the
counts CSV, filter to one hour, optionally narrow to weekend/weekday, then
group by node and take the mean vehicle_count. Operations copied from
fetch_observed_counts(). Repeated calibration calls re-run this filter+groupby.
"""
from __future__ import annotations

import os

from _harness import finalize, main, stage

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(_REPO_ROOT, "data", "model", "training_dataset.csv")

# representative time context (evening peak, weekday)
HOUR = 17
IS_WEEKEND = 0


def pipeline(xp, sync):
    t = {}
    with stage(t, "read_csv", sync):
        df = xp.read_csv(CSV)

    with stage(t, "filter_hour", sync):
        sub = df[df["hour"] == HOUR]
    with stage(t, "filter_weekend", sync):
        if "is_weekend" in df.columns:
            match = sub[sub["is_weekend"] == IS_WEEKEND]
            if len(match) >= 20:
                sub = match

    with stage(t, "groupby_mean", sync):
        grouped = sub.groupby("node_id")["vehicle_count"].mean()

    # The real code materializes a {node: mean} dict; for cuDF that requires a
    # host hop. Time it so the comparison reflects the full call-site cost.
    with stage(t, "to_dict", sync):
        host = grouped.to_pandas() if xp.__name__ == "cudf" else grouped
        result = {int(n): float(c) for n, c in host.items() if c > 0}

    return finalize(t), f"{len(result):,} nodes"


TITLE = "odme_calibrate.py : fetch_observed_counts (filter + groupby mean)"

if __name__ == "__main__":
    main(TITLE, pipeline)
