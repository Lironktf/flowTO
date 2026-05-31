"""Restricted-road guardrail lookup for the closure warning.

A full closure on a "Completely Prohibited" provincial highway (MTO) or a City
of Toronto municipal expressway is not permitted. The restricted edge set is
derived offline from the Toronto Centreline (TCL) by
``scripts/build_restricted_roads.py`` and stored as a small committed artifact;
this module loads it and classifies edge ids on demand.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

MTO_PROHIBITED = "mto_prohibited"
MUNICIPAL_EXPRESSWAY = "municipal_expressway"

CATEGORY_REASON = {
    MTO_PROHIBITED: (
        "This is a Completely Prohibited highway under provincial (MTO) "
        "jurisdiction. Full closures cannot be simulated here."
    ),
    MUNICIPAL_EXPRESSWAY: (
        "This is a City of Toronto municipal expressway. Full closures cannot " "be simulated here."
    ),
}


def _repo_data_dir() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.abspath(os.environ.get("TS_DATA_DIR", os.path.join(repo_root, "data")))


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, dict]:
    """Return ``{edge_id: {"category", "label"}}`` from the artifact at ``path``."""
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        artifact = json.load(fh)
    edges = artifact.get("edges", {})
    return edges if isinstance(edges, dict) else {}


def _artifact_path(data_dir: str | None) -> str:
    return os.path.join(
        os.path.abspath(data_dir or _repo_data_dir()), "graph", "restricted_roads.json"
    )


def restricted_index(data_dir: str | None = None) -> dict[str, dict]:
    """The full ``{edge_id: {category, label}}`` map (empty if the artifact is absent)."""
    return _load(_artifact_path(data_dir))


def classify_edge(edge_id: str, data_dir: str | None = None) -> dict | None:
    """Return ``{category, label, reason}`` for a restricted edge, else ``None``."""
    entry = restricted_index(data_dir).get(edge_id)
    if not entry:
        return None
    category = entry.get("category")
    return {
        "category": category,
        "label": entry.get("label"),
        "reason": CATEGORY_REASON.get(category, "Full closures are not permitted on this road."),
    }
