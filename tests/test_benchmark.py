"""P13 §G benchmark harness — local (torch-free) tests.

Covers the config registry (prune = column drops), the NumPy metrics, the
group-wise spatial-holdout split (no centreline_id leakage), and the A/B
comparison + report rendering.
"""

from __future__ import annotations

import numpy as np
import pytest

from torontosim.feedback.benchmark import (
    compare_configs,
    evaluate,
    get_config,
    mae,
    r2,
    rank_topk_overlap,
    render_markdown,
    rmse,
    risk_accuracy,
    spatial_holdout_split,
    write_report,
)
from torontosim.feedback.benchmark.configs import (
    BASELINE_EDGE_FEATURES,
    BASELINE_NODE_FEATURES,
    REGISTRY,
    select_columns,
)


# ── configs ─────────────────────────────────────────────────────────────────────
def test_baseline_feature_counts_match_utils():
    assert len(BASELINE_NODE_FEATURES) == 7
    assert len(BASELINE_EDGE_FEATURES) == 21  # 11 scalar + 10 road_class one-hot


def test_baseline_config_drops_nothing():
    cfg = get_config("baseline")
    assert cfg.kept_node(BASELINE_NODE_FEATURES) == BASELINE_NODE_FEATURES
    assert cfg.kept_edge(BASELINE_EDGE_FEATURES) == BASELINE_EDGE_FEATURES


def test_pruned_drops_demand_priors_and_redundant():
    cfg = get_config("pruned")
    node = cfg.kept_node(BASELINE_NODE_FEATURES)
    edge = cfg.kept_edge(BASELINE_EDGE_FEATURES)
    # demand prior + redundant + memorization gone
    for gone in ("distance_to_downtown_km", "degree", "lat", "lon", "pagerank"):
        assert gone not in node
    for gone in ("road_class_rank", "from_node_degree", "to_node_degree"):
        assert gone not in edge
    # structural keepers retained
    assert "in_degree" in node and "out_degree" in node
    assert "capacity" in edge and "road_class_motorway" in edge
    assert cfg.head == "residual_identity"


def test_ablations_isolate_one_change():
    assert get_config("ablate_downtown").drop_node == frozenset({"distance_to_downtown_km"})
    red = get_config("ablate_redundant")
    assert "degree" in red.drop_node and "road_class_rank" in red.drop_edge


def test_select_columns_subsets_in_keep_order():
    mat = np.arange(12).reshape(3, 4)
    names = ["a", "b", "c", "d"]
    sub = select_columns(mat, names, ["c", "a"])
    assert sub.shape == (3, 2)
    assert sub[0].tolist() == [2, 0]  # column c then a


def test_select_columns_raises_on_unknown():
    mat = np.zeros((2, 2))
    try:
        select_columns(mat, ["a", "b"], ["a", "z"])
    except KeyError as e:
        assert "z" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError for unknown column")


# ── metrics ─────────────────────────────────────────────────────────────────────
def test_error_metrics_known_values():
    pred = [1.0, 2.0, 3.0]
    target = [1.0, 2.0, 5.0]  # only last differs by 2
    assert mae(pred, target) == 2 / 3
    assert rmse(pred, target) == np.sqrt(4 / 3)
    assert r2(pred, [1.0, 1.0, 1.0]) == 0.0  # constant target, nonzero residual


def test_perfect_prediction_scores():
    x = [0.2, 0.6, 1.1]
    assert mae(x, x) == 0.0 and rmse(x, x) == 0.0
    assert r2(x, x) == 1.0
    assert risk_accuracy(x, x) == 1.0


def test_risk_accuracy_buckets():
    # 0.2→low, 0.6→moderate, 1.2→severe ; pred shifts the middle one up a bucket
    pred = [0.2, 0.8, 1.2]
    target = [0.2, 0.6, 1.2]
    assert risk_accuracy(pred, target) == 2 / 3


def test_rank_topk_overlap():
    pred = [0.0, 5.0, -9.0, 1.0]      # top-2 by |.|: idx 2,1
    target = [0.0, 8.0, -9.0, 2.0]    # top-2 by |.|: idx 2,1
    assert rank_topk_overlap(pred, target, 2) == 1.0
    target2 = [10.0, 0.1, 0.1, 9.0]   # top-2: idx 0,3 → no overlap with 2,1
    assert rank_topk_overlap(pred, target2, 2) == 0.0


def test_evaluate_includes_topk_when_asked():
    out = evaluate([0.1, 0.9], [0.1, 0.9], topk=1)
    assert "rank_top1_overlap" in out and out["mae"] == 0.0


# ── spatial holdout ──────────────────────────────────────────────────────────────
def test_spatial_holdout_no_group_leakage():
    groups = np.array(["A", "A", "B", "B", "C", "C", "D", "D"])
    train, test = spatial_holdout_split(groups, test_frac=0.5, seed=1)
    assert not (train & test).any()           # disjoint
    assert (train | test).all()               # covers all
    # every group is wholly in train xor test
    for g in np.unique(groups):
        idx = groups == g
        assert train[idx].all() or test[idx].all()


def test_spatial_holdout_deterministic():
    groups = np.array([i // 2 for i in range(20)])
    a = spatial_holdout_split(groups, seed=7)
    b = spatial_holdout_split(groups, seed=7)
    assert np.array_equal(a[1], b[1])


# ── compare + report ─────────────────────────────────────────────────────────────
def test_compare_picks_correct_winners():
    results = {
        "baseline": {"mae": 0.20, "r2": 0.80},
        "pruned": {"mae": 0.15, "r2": 0.85},
    }
    cmp = compare_configs(results, reference="baseline")
    assert cmp["metrics"]["mae"]["winner"] == "pruned"       # lower better
    assert cmp["metrics"]["r2"]["winner"] == "pruned"        # higher better
    assert cmp["metrics"]["mae"]["delta_vs_reference"]["pruned"] == pytest.approx(-0.05)


def test_render_and_write_report(tmp_path):
    results = {"baseline": {"mae": 0.2}, "pruned": {"mae": 0.1}}
    cmp = compare_configs(results)
    md = render_markdown(cmp)
    assert "pruned" in md and "✅" in md
    jp, mp = tmp_path / "r.json", tmp_path / "r.md"
    write_report(cmp, jp, mp)
    assert jp.exists() and mp.exists() and "mae" in mp.read_text()
