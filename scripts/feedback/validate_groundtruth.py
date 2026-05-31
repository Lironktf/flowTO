"""End-to-end smoke of P14 Phases 0-3 on the REAL CART snapshot + TMC (GB10 only).

Runs clean -> spatial -> temporal -> labels on the real files and prints the headline
counts, to validate against the v1 prototype's documented numbers. A throwaway driver
until the Phase-7 CLI lands.

    python scripts/feedback/validate_groundtruth.py data/dataset/v3.csv data/raw/tmc.csv
"""

from __future__ import annotations

import sys

import pandas as pd

from torontosim.feedback.groundtruth.clean import clean_restrictions
from torontosim.feedback.groundtruth.labels import build_labels
from torontosim.feedback.groundtruth.openings import (
    after_aggregate,
    build_opening_labels,
    split_after,
)
from torontosim.feedback.groundtruth.package import (
    build_manifest,
    combine_interventions,
    grouped_split,
)
from torontosim.feedback.groundtruth.spatial import spatial_join, tmc_sites
from torontosim.feedback.groundtruth.temporal import (
    during_aggregate,
    split_during_pre,
    tmc_observations,
)


def main() -> None:
    v3_path, tmc_path = sys.argv[1], sys.argv[2]

    restrictions = clean_restrictions(v3_path)
    print(f"restrictions: {len(restrictions)} (dropped {restrictions.attrs.get('dropped')})")

    tmc = pd.read_csv(tmc_path, low_memory=False)
    obs = tmc_observations(tmc)
    sites = tmc_sites(tmc)
    print(f"TMC rows: {len(tmc):,} · observations: {len(obs):,} · sites: {len(sites):,}")

    pairs = spatial_join(sites, restrictions, radius_m=500.0)
    print(f"pairs <=500m: {len(pairs):,} · restrictions w/ a neighbour site: {pairs['ID'].nunique()}")

    during, pre = split_during_pre(pairs, obs)
    dagg = during_aggregate(pairs, obs)
    print(f"during surveys: {len(during):,} · during_agg rows: {len(dagg):,}")

    closures = build_labels(dagg, during, pre)
    bl = closures[closures["has_baseline"] == 1]
    up = int((bl["direction"] == 1).sum())
    down = int((bl["direction"] == 0).sum())
    print("\n=== CLOSURES ===")
    print(f"rows (restriction x site): {len(closures):,}")
    print(f"restrictions represented:  {closures['ID'].nunique()}")
    print(f"rows WITH baseline:        {len(bl)}  (up={up}, down={down})")
    print(f"  significant (|sigma|>1.5): {int((bl['significant'] == 1).sum())}")

    # openings: after-reopening vs during-closure baseline
    after = split_after(pairs, obs)
    aagg = after_aggregate(after)
    openings = build_opening_labels(aagg, after, during)
    obl = openings[openings["has_baseline"] == 1] if len(openings) else openings
    print("\n=== OPENINGS ===")
    print(f"rows: {len(openings):,} · with baseline: {len(obl)}")

    # package: combine + leak-free split + manifest
    combined = grouped_split(combine_interventions(closures, openings))
    manifest = build_manifest(combined)
    print("\n=== PACKAGED MANIFEST ===")
    for k in ("rows", "closures", "openings", "restrictions", "with_baseline",
              "direction_up", "direction_down", "confounder_clean", "split"):
        print(f"  {k}: {manifest[k]}")


if __name__ == "__main__":
    main()
