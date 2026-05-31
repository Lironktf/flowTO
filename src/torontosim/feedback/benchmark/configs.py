"""Feature configs for the same-task A/B benchmark.

A config is defined by the columns it **drops** from the baseline feature vectors,
applied by *name* against whatever the built dataset actually reports as its
``node_feature_names`` / ``edge_feature_names`` / ``context_feature_names``. Defining
configs as drops (not fixed lists) means they stay correct even if the dataset's
column order or the road-class one-hot set changes — only exact-name matches are
removed.

The baseline name lists mirror ``models/gnn/utils.py`` (kept here as plain strings
so this module imports without torch). See ``docs/specs/13-feedback-loop.md`` §C.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ── Baseline feature names (mirror models/gnn/utils.py) ─────────────────────────
ROAD_CLASS_ORDER = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "service",
    "unclassified",
    "living_street",
    "other",
]
BASELINE_NODE_FEATURES = [
    "lat",
    "lon",
    "degree",
    "in_degree",
    "out_degree",
    "distance_to_downtown_km",
    "pagerank",
]
BASELINE_EDGE_FEATURES = [
    "length_m",
    "road_class_rank",
    "lanes",
    "speed_kmh",
    "capacity",
    "base_time_min",
    "one_way",
    "bearing_sin",
    "bearing_cos",
    "from_node_degree",
    "to_node_degree",
    *[f"road_class_{name}" for name in ROAD_CLASS_ORDER],
]
BASELINE_CONTEXT_FEATURES = [
    "hour_norm",
    "day_of_week_norm",
    "month_norm",
    "is_weekend",
    "rush_hour",
    "weather_clear",
    "weather_rain",
    "weather_snow",
    "temperature_c_norm",
    "precipitation_mm_norm",
    "season_winter",
    "season_spring",
    "season_summer",
    "season_fall",
]


@dataclass(frozen=True)
class FeatureConfig:
    """A named feature set, expressed as columns dropped from the baseline.

    ``head`` records the prediction head the config implies — the baseline uses a
    softplus pressure head; pruned/residual variants drop softplus for a signed
    head (see §C). It is metadata here; the torch runner consumes it.
    """

    name: str
    drop_node: frozenset[str] = field(default_factory=frozenset)
    drop_edge: frozenset[str] = field(default_factory=frozenset)
    drop_context: frozenset[str] = field(default_factory=frozenset)
    head: str = "pressure_softplus"
    note: str = ""

    def kept_node(self, all_names: list[str]) -> list[str]:
        return [n for n in all_names if n not in self.drop_node]

    def kept_edge(self, all_names: list[str]) -> list[str]:
        return [n for n in all_names if n not in self.drop_edge]

    def kept_context(self, all_names: list[str]) -> list[str]:
        return [n for n in all_names if n not in self.drop_context]


def select_columns(matrix: np.ndarray, all_names: list[str], keep_names: list[str]) -> np.ndarray:
    """Return ``matrix`` restricted to ``keep_names`` columns, in keep order.

    ``matrix`` is ``[rows, len(all_names)]``. Raises if a kept name is absent so a
    typo fails loudly rather than silently dropping a feature.
    """
    index = {name: i for i, name in enumerate(all_names)}
    missing = [n for n in keep_names if n not in index]
    if missing:
        raise KeyError(f"keep_names not in all_names: {missing}")
    cols = [index[n] for n in keep_names]
    return matrix[:, cols]


# ── Registry ────────────────────────────────────────────────────────────────────
# Dead-weight drops confirmed by research/08 (small win): redundant dups + the
# distance_to_downtown demand prior + dead-by-default pagerank.
_DEAD_NODE = frozenset({"degree", "distance_to_downtown_km", "pagerank"})
_DEAD_EDGE = frozenset({"road_class_rank", "from_node_degree", "to_node_degree"})

REGISTRY: dict[str, FeatureConfig] = {
    "baseline": FeatureConfig(
        name="baseline",
        note="main's full 7-node / 21-edge / 14-context set, softplus pressure head",
    ),
    # the recommended set (research/08): drop dead weight, KEEP lat/lon (as a
    # learned PE in the residual model) since dropping coords cost ~9% MAE.
    "lean": FeatureConfig(
        name="lean",
        drop_node=_DEAD_NODE,
        drop_edge=_DEAD_EDGE,
        head="residual_identity",
        note="data-backed lean set: drop dead weight, keep coords (→ learned PE)",
    ),
    # aggressive ablation — also drops lat/lon; benchmarked clearly worse (~9% MAE).
    # kept as the memorization probe, NOT the recommended config.
    "pruned": FeatureConfig(
        name="pruned",
        drop_node=_DEAD_NODE | frozenset({"lat", "lon"}),
        drop_edge=_DEAD_EDGE,
        head="residual_identity",
        note="aggressive: drops coords too (memorization probe; worse — research/08)",
    ),
    # ablations isolating each prune so we can attribute any delta
    "ablate_downtown": FeatureConfig(
        name="ablate_downtown",
        drop_node=frozenset({"distance_to_downtown_km"}),
        note="baseline minus distance_to_downtown only",
    ),
    "ablate_redundant": FeatureConfig(
        name="ablate_redundant",
        drop_node=frozenset({"degree"}),
        drop_edge=frozenset({"road_class_rank", "from_node_degree", "to_node_degree"}),
        note="baseline minus mathematically-redundant features only",
    ),
}


def get_config(name: str) -> FeatureConfig:
    if name not in REGISTRY:
        raise KeyError(f"unknown config {name!r}; have {sorted(REGISTRY)}")
    return REGISTRY[name]
