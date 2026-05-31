"""GNN benchmark & regression harness (P13 §G).

Two comparisons, kept distinct (see ``docs/specs/13-feedback-loop.md`` §G):

1. **Same-task A/B** — is the branch's feature-pruned GNN better than main's on the
   open-road *pressure* task? Both configs train on the SAME frozen dataset + split
   + seed; only the feature set varies (a config = a set of dropped columns), so any
   delta is the model's, not env/data skew. Metrics: val MAE/RMSE/R²/risk-accuracy +
   a spatial-holdout (unseen ``centreline_id``) generalization probe.
2. **New-capability** — does the closure GNN beat the deterministic sim? (the
   activation gate, ``feedback/gate.py`` — added later.)

The config registry, metrics, comparison, and reporting here are **pure NumPy** so
they run and unit-test locally without torch/PyG. The per-config train/eval that
produces the metrics needs torch and runs on the GB10/Spark (``benchmark.run`` +
``scripts/spark/benchmark_gnn.sh``, added later).
"""

from .configs import REGISTRY, FeatureConfig, get_config
from .compare import compare_configs, render_markdown, write_report
from .metrics import (
    evaluate,
    mae,
    r2,
    rank_topk_overlap,
    risk_accuracy,
    rmse,
    spatial_holdout_split,
)

__all__ = [
    "REGISTRY",
    "FeatureConfig",
    "get_config",
    "compare_configs",
    "render_markdown",
    "write_report",
    "evaluate",
    "mae",
    "rmse",
    "r2",
    "risk_accuracy",
    "rank_topk_overlap",
    "spatial_holdout_split",
]
