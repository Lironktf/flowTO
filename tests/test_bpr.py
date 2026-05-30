"""P04 T04.1 — BPR volume-delay function tests."""

from __future__ import annotations

import math

from torontosim.simulation.bpr import bpr_time


def test_bpr_zero_volume_is_freeflow():
    assert bpr_time(10.0, 0.0, 100.0) == 10.0


def test_bpr_at_capacity_is_t0_times_1_15():
    # v == c -> t0 * (1 + 0.15 * 1^4) = t0 * 1.15
    assert math.isclose(bpr_time(10.0, 100.0, 100.0), 11.5, rel_tol=1e-9)


def test_bpr_zero_capacity_is_inf():
    assert bpr_time(10.0, 50.0, 0.0) == float("inf")


def test_bpr_monotonic_increasing_in_volume():
    t0, c = 5.0, 200.0
    prev = -1.0
    for v in range(0, 1000, 25):
        t = bpr_time(t0, float(v), c)
        assert t >= prev
        prev = t


def test_bpr_custom_alpha_beta():
    # alpha=0.5, beta=2, v=c -> t0*(1+0.5) = 1.5*t0
    assert math.isclose(bpr_time(4.0, 10.0, 10.0, alpha=0.5, beta=2.0), 6.0, rel_tol=1e-9)
