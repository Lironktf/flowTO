"""P14 Phase 7 — packaging, leak-free split & manifest tests (CPU pandas; GB10)."""

from __future__ import annotations

import pandas as pd

from torontosim.feedback.groundtruth.package import (
    build_manifest,
    combine_interventions,
    grouped_split,
    write_dataset,
)


def _closures():
    return pd.DataFrame(
        {
            "ID": ["r1", "r1", "r2"],
            "centreline_id": ["A", "B", "C"],
            "intervention_sign": ["closure"] * 3,
            "has_baseline": [1, 1, 0],
            "direction": pd.array([0, 1, pd.NA], dtype="Int8"),
            "confounder_dominated": [0, 1, 0],
        }
    )


def _openings():
    return pd.DataFrame(
        {
            "ID": ["r3"],
            "centreline_id": ["D"],
            "intervention_sign": ["opening"],
            "has_baseline": [1],
            "direction": pd.array([1], dtype="Int8"),
            "confounder_dominated": [0],
        }
    )


def test_combine_tags_signs():
    df = combine_interventions(_closures(), _openings())
    assert len(df) == 4
    assert set(df["intervention_sign"]) == {"closure", "opening"}


def test_grouped_split_no_centreline_leakage():
    df = combine_interventions(_closures(), _openings())
    # duplicate a centreline across rows to prove it never straddles the split
    df = pd.concat([df, df.assign(ID="dup")], ignore_index=True)
    out = grouped_split(df, test_frac=0.5, seed=1)
    for cid, grp in out.groupby("centreline_id"):
        assert grp["split"].nunique() == 1  # every site wholly train xor test


def test_grouped_split_deterministic():
    df = combine_interventions(_closures(), _openings())
    a = grouped_split(df, seed=7)["split"].tolist()
    b = grouped_split(df, seed=7)["split"].tolist()
    assert a == b


def test_manifest_counts_and_caveats():
    df = grouped_split(combine_interventions(_closures(), _openings()), test_frac=0.5, seed=1)
    m = build_manifest(df)
    assert m["rows"] == 4 and m["closures"] == 3 and m["openings"] == 1
    assert m["with_baseline"] == 3
    assert m["direction_up"] == 2 and m["direction_down"] == 1
    assert m["confounder_clean"] == 3            # one row is confounder_dominated
    assert m["caveats"] and isinstance(m["caveats"], list)
    assert sum(m["split"].values()) == 4


def test_write_dataset_roundtrip(tmp_path):
    df = grouped_split(combine_interventions(_closures(), _openings()))
    m = write_dataset(
        df,
        parquet_path=tmp_path / "x.parquet",
        csv_path=tmp_path / "x.csv",
        manifest_path=tmp_path / "x.manifest.json",
    )
    assert (tmp_path / "x.parquet").exists() and (tmp_path / "x.csv").exists()
    back = pd.read_parquet(tmp_path / "x.parquet")
    assert len(back) == 4 and m["rows"] == 4
