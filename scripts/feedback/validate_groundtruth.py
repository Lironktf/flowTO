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

    labels = build_labels(dagg, during, pre)
    bl = labels[labels["has_baseline"] == 1]
    up = int((bl["direction"] == 1).sum())
    down = int((bl["direction"] == 0).sum())
    print("\n=== LABELS ===")
    print(f"rows (restriction x site): {len(labels):,}")
    print(f"restrictions represented:  {labels['ID'].nunique()}")
    print(f"rows WITH baseline:        {len(bl)}  (up={up}, down={down})")
    print(f"  significant (|sigma|>1.5): {int((bl['significant'] == 1).sum())}")
    print(f"  baseline_match mix:        {labels['baseline_match'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
