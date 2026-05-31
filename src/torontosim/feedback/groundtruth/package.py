"""P14 Phase 7 — packaging, leak-free split & coverage manifest.

Combine closure + opening labels into one artifact, assign a **grouped train/test
split by ``centreline_id``** (a site never appears in both — prevents the spatial
leakage that would inflate P13's activation gate), and write a machine-readable
manifest of counts + honesty caveats so downstream can't mistake thin for complete.

See ``docs/specs/14-closure-dataset.md`` Phase 7.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CAVEATS = [
    "TMC counts are sparse manual snapshots — most closures have no in-window survey.",
    "Openings need a survey after reopening at the same site → far fewer rows than closures.",
    "Labels are SIGNED (closures usually lower volume on the segment, raise it on detours).",
    "Rows without a baseline have null deltas, not zero (no fabrication).",
    "confounder_dominated rows are excluded from the clean training subset.",
]


def combine_interventions(closures: pd.DataFrame, openings: pd.DataFrame) -> pd.DataFrame:
    """Stack closure + opening label frames into one intervention-impact frame."""
    frames = [f for f in (closures, openings) if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def grouped_split(
    df: pd.DataFrame, *, group_col: str = "centreline_id", test_frac: float = 0.2, seed: int = 42
) -> pd.DataFrame:
    """Add a ``split`` column assigning whole ``group_col`` groups to train/test.

    Deterministic for a fixed seed; guarantees no group appears in both splits.
    """
    out = df.copy()
    if out.empty:
        out["split"] = pd.Series(dtype="object")
        return out
    groups = out[group_col].unique()
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(groups))
    n_test = max(1, int(round(test_frac * len(groups))))
    test_groups = set(groups[order[:n_test]].tolist())
    out["split"] = np.where(out[group_col].isin(test_groups), "test", "train")
    return out


def build_manifest(df: pd.DataFrame) -> dict:
    """Counts + honesty caveats describing the artifact."""
    sign = df["intervention_sign"] if "intervention_sign" in df else pd.Series([], dtype="object")
    bl = df[df["has_baseline"] == 1] if "has_baseline" in df else df.iloc[0:0]
    clean = (
        df["confounder_dominated"] == 0
        if "confounder_dominated" in df
        else pd.Series(True, index=df.index)
    )
    return {
        "rows": int(len(df)),
        "closures": int((sign == "closure").sum()),
        "openings": int((sign == "opening").sum()),
        "restrictions": int(df["ID"].nunique()) if "ID" in df else 0,
        "with_baseline": int(len(bl)),
        "direction_up": int((bl["direction"] == 1).sum()) if "direction" in bl else 0,
        "direction_down": int((bl["direction"] == 0).sum()) if "direction" in bl else 0,
        "confounder_clean": int(clean.sum()),
        "split": df["split"].value_counts().to_dict() if "split" in df else {},
        "caveats": CAVEATS,
    }


def write_dataset(
    df: pd.DataFrame,
    *,
    parquet_path: str | Path,
    csv_path: str | Path,
    manifest_path: str | Path,
) -> dict:
    """Write the parquet + CSV view + manifest; return the manifest."""
    parquet_path, csv_path, manifest_path = map(Path, (parquet_path, csv_path, manifest_path))
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(df)
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
