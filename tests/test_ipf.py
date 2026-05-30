"""P03 Stage-1 IPF (Furness) tests: matches marginals, deterministic."""

from __future__ import annotations

import numpy as np

from torontosim.model.ipf import ipf


def test_ipf_matches_marginals():
    seed = np.array([[1.0, 2.0, 1.0], [2.0, 1.0, 3.0], [1.0, 1.0, 1.0]])
    row = np.array([10.0, 20.0, 30.0])
    col = np.array([25.0, 15.0, 20.0])
    out = ipf(seed, row, col)
    assert np.allclose(out.sum(axis=1), row, atol=1e-6)
    assert np.allclose(out.sum(axis=0), col, atol=1e-6)


def test_ipf_deterministic():
    seed = np.array([[1.0, 3.0], [2.0, 1.0]])
    row = np.array([5.0, 7.0])
    col = np.array([4.0, 8.0])
    a = ipf(seed, row, col)
    b = ipf(seed, row, col)
    assert np.array_equal(a, b)


def test_sparse_calibrate_ipf_balances_to_strengths():
    from torontosim.model.generate_od_matrix import _calibrate_ipf

    # Three origins, three dests; gravity values arbitrary.
    pairs = [
        ("o1", "d1", 1.0),
        ("o1", "d2", 2.0),
        ("o2", "d1", 3.0),
        ("o2", "d2", 1.0),
        ("o3", "d2", 2.0),
    ]
    origin_strength = {"o1": 10.0, "o2": 20.0, "o3": 5.0}
    dest_strength = {"d1": 12.0, "d2": 23.0}
    out = _calibrate_ipf(pairs, origin_strength, dest_strength)

    # Row sums should track production marginals (renormalized total).
    row = {}
    for i, _j, v in out:
        row[i] = row.get(i, 0.0) + v
    # o2 has the largest production -> largest row sum.
    assert row["o2"] > row["o1"] > row["o3"]
    # Structural zero preserved: ("o3","d1") never appears.
    assert all(not (i == "o3" and j == "d1") for i, j, _ in out)


def test_ipf_handles_structural_zeros():
    # A zero seed cell stays zero (no trips can be created where seed forbids).
    seed = np.array([[0.0, 1.0], [1.0, 1.0]])
    row = np.array([3.0, 4.0])
    col = np.array([2.0, 5.0])
    out = ipf(seed, row, col)
    assert out[0, 0] == 0.0
    assert np.allclose(out.sum(axis=1), row, atol=1e-6)
