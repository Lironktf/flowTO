"""The demand-model contract + provenance manifest (modularity & reproducibility).

A *demand model* is anything that lets ``predict_node_demand(graph, model, ctx)``
return ``{node_id: vehicle_demand}``. Two shapes satisfy the contract today:

1. **Tabular** — an object with ``.predict(X)`` over rows in ``FEATURE_ORDER``
   (sklearn/xgboost estimators, ``HeuristicDemandModel``). Carried in a payload
   dict ``{"kind", "model", "feature_order", ...}`` or passed bare.
2. **GNN** — a payload ``{"kind": "gnn", "model_path", "dataset_path",
   "graph_path", "feature_order"}`` routed through the GraphSAGE adapter.

To stay swappable, a NEW model only has to either (a) expose ``.predict(X)`` over
``FEATURE_ORDER`` — then it drops straight in — or (b) be registered as a new
``kind`` (one branch in ``predict_node_demand``). Either way it should ship a
``ModelManifest`` so the pipeline can verify compatibility and reproduce results.

The manifest is the reproducibility unit: it pins the feature schema, the seed,
a hash of the training data, the git commit, and the metrics, so a model file
found later can be traced to exactly how it was produced and checked for
compatibility *before* it is trusted in a simulation.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

import numpy as np

# Bump when the saved payload / manifest structure changes in a breaking way.
# load-time compatibility checks compare against this.
SCHEMA_VERSION = 1


@runtime_checkable
class DemandModel(Protocol):
    """Structural contract for a tabular demand model.

    Anything matching this (an sklearn/xgboost estimator, the heuristic model, a
    new regressor) is a valid drop-in for the tabular path — no core changes.
    """

    feature_order: list[str]

    def predict(self, X: np.ndarray) -> np.ndarray:  # rows in feature_order -> per-node demand
        ...


@dataclass
class ModelManifest:
    """Provenance + compatibility metadata that travels with a saved model."""

    kind: str
    feature_order: list[str]
    target: str = "vehicle_count"
    schema_version: int = SCHEMA_VERSION
    seed: Optional[int] = None
    backend: Optional[str] = None
    training_data_path: Optional[str] = None
    training_data_sha256: Optional[str] = None
    training_rows: Optional[int] = None
    metrics: dict = field(default_factory=dict)
    git_commit: Optional[str] = None
    created_at: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_commit(cwd: Optional[str] = None) -> Optional[str]:
    """Short git SHA of the working tree, or None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001 — git missing / not a repo
        return None


def file_sha256(path: str, *, chunk: int = 1 << 20) -> Optional[str]:
    """SHA-256 of a file's bytes (training data), or None if unreadable."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(chunk), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:  # noqa: BLE001
        return None


def build_manifest(
    *,
    kind: str,
    feature_order: list[str],
    target: str = "vehicle_count",
    seed: Optional[int] = None,
    backend: Optional[str] = None,
    training_data_path: Optional[str] = None,
    training_rows: Optional[int] = None,
    metrics: Optional[dict] = None,
    notes: Optional[str] = None,
) -> ModelManifest:
    """Assemble a manifest, computing the data hash / git sha / timestamp."""
    return ModelManifest(
        kind=kind,
        feature_order=list(feature_order),
        target=target,
        seed=seed,
        backend=backend,
        training_data_path=training_data_path,
        training_data_sha256=file_sha256(training_data_path) if training_data_path else None,
        training_rows=training_rows,
        metrics=dict(metrics or {}),
        git_commit=git_commit(),
        created_at=utc_now_iso(),
        notes=notes,
    )


def manifest_from_payload(payload: Any) -> Optional[ModelManifest]:
    """Recover a manifest from a loaded payload dict, tolerating older models.

    Older payloads have no ``manifest`` key but do carry ``feature_order`` /
    ``kind`` / ``metrics`` at the top level; we reconstruct a partial manifest
    from those so legacy models still report what they can.
    """
    if not isinstance(payload, dict):
        return None
    m = payload.get("manifest")
    if isinstance(m, dict):
        known = {f for f in ModelManifest.__dataclass_fields__}
        return ModelManifest(**{k: v for k, v in m.items() if k in known})
    if "feature_order" in payload or "kind" in payload:
        return ModelManifest(
            kind=str(payload.get("kind", "unknown")),
            feature_order=list(payload.get("feature_order", [])),
            target=str(payload.get("target", "vehicle_count")),
            schema_version=int(payload.get("schema_version", 0)),  # 0 => pre-manifest
            metrics=dict(payload.get("metrics", {})),
        )
    return None


def check_compatible(payload: Any, *, expected_feature_order: list[str]) -> list[str]:
    """Return a list of compatibility problems ([] == compatible).

    Validates the feature-order match (the hard requirement for the tabular
    path) and flags a schema-version mismatch. Callers decide whether to warn
    or raise.
    """
    problems: list[str] = []
    man = manifest_from_payload(payload)
    if man is None:
        return ["model carries no manifest or feature_order; cannot verify compatibility"]

    if man.schema_version > SCHEMA_VERSION:
        problems.append(
            f"model schema_version {man.schema_version} is newer than this code "
            f"({SCHEMA_VERSION}); update flowTO before using it"
        )

    # GNN models don't use the tabular FEATURE_ORDER row contract.
    if (
        man.kind != "gnn"
        and man.feature_order
        and man.feature_order != list(expected_feature_order)
    ):
        problems.append(
            "feature_order mismatch:\n"
            f"  model: {man.feature_order}\n"
            f"  code:  {list(expected_feature_order)}"
        )
    return problems
