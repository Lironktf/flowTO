"""P03 Stage-2 ODME (IPF-on-counts) tests.

Synthetic network with a known true OD: assign it to get "observed" link
counts, perturb the seed away from truth, then check ODME-from-counts moves the
seed back toward truth (error decreases) without diverging.
"""

from __future__ import annotations

from torontosim.model.odme import assign_to_links, odme_ipf_counts, total_abs_error

# Two OD pairs over a tiny network; each uses a fixed link path.
PATHS = {
    ("A", "X"): ["l1", "l3"],
    ("B", "X"): ["l2", "l3"],
}


def _path_of(o, d):
    return PATHS[(o, d)]


TRUE_OD = {("A", "X"): 100.0, ("B", "X"): 60.0}


def test_assign_to_links_sums_paths():
    links = assign_to_links(TRUE_OD, _path_of)
    assert links["l1"] == 100.0
    assert links["l2"] == 60.0
    assert links["l3"] == 160.0  # shared link carries both


def test_odme_moves_seed_toward_truth():
    observed = assign_to_links(TRUE_OD, _path_of)
    # Seed is wrong (both pairs underestimated/overestimated).
    seed = {("A", "X"): 40.0, ("B", "X"): 120.0}

    before = total_abs_error(assign_to_links(seed, _path_of), observed)
    calibrated = odme_ipf_counts(seed, observed, _path_of, max_iter=50)
    after = total_abs_error(assign_to_links(calibrated, _path_of), observed)

    assert after < before  # got closer to matching observed counts
    assert after <= before  # never diverges
    # All trips stay non-negative and finite.
    assert all(v >= 0 and v == v for v in calibrated.values())


def test_odme_deterministic():
    observed = assign_to_links(TRUE_OD, _path_of)
    seed = {("A", "X"): 40.0, ("B", "X"): 120.0}
    a = odme_ipf_counts(seed, observed, _path_of, max_iter=20)
    b = odme_ipf_counts(seed, observed, _path_of, max_iter=20)
    assert a == b
