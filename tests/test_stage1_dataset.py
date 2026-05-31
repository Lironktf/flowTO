"""P13 §C — scenario channel assembly tests (pure NumPy; runs anywhere)."""

from __future__ import annotations

import numpy as np

from torontosim.feedback.dataset import scenario_edge_channels


def test_channels_mask_capmult_and_residual_target():
    edge_order = ["e0", "e1", "e2"]
    capacity = {"e0": 100.0, "e1": 100.0, "e2": 100.0}
    # closing e0: e0 loses its flow; e1 (detour) gains; e2 absent this scenario
    scn = {
        "e0": ("closure", "e0", 100.0, -100.0),
        "e1": ("closure", "e0", 50.0, 40.0),
    }
    chan, target = scenario_edge_channels(scn, edge_order, capacity)
    # e0 is the closed edge → mask 1, capacity_mult 0
    assert chan[0].tolist() == [1.0, 0.0, 100.0, 1.0]    # mask, cmult, sim_open, sim_open/cap
    assert target[0] == -1.0                             # delta_flow/cap = -100/100
    # e1 is a detour → mask 0, capacity_mult 1
    assert chan[1].tolist() == [0.0, 1.0, 50.0, 0.5]
    assert target[1] == 0.4                              # 40/100
    # e2 absent → all zero
    assert chan[2].tolist() == [0.0, 1.0, 0.0, 0.0]
    assert target[2] == 0.0


def test_opening_sets_capacity_mult_above_one():
    chan, _ = scenario_edge_channels(
        {"e0": ("opening", "e0", 80.0, 30.0)}, ["e0"], {"e0": 100.0}, capacity_up=1.5
    )
    assert chan[0, 0] == 1.0 and chan[0, 1] == 1.5       # mask, capacity_mult (added capacity)


def test_missing_capacity_defaults_safely():
    chan, target = scenario_edge_channels(
        {"e0": ("closure", "e0", 10.0, -10.0)}, ["e0"], {}
    )
    assert np.isfinite(chan).all() and np.isfinite(target).all()
