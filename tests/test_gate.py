"""P13 §D — activation gate tests (pure NumPy; runs anywhere)."""

from __future__ import annotations

import numpy as np

from torontosim.feedback.gate import activation_gate

rng = np.random.default_rng(0)
R_OBS = rng.normal(size=40)
R_SIM = R_OBS + rng.normal(scale=0.5, size=40)  # sim is a noisy estimate of reality


def test_gnn_must_beat_the_sim_to_ship():
    perfect = activation_gate(R_OBS, R_OBS, R_SIM, min_n=10)  # GNN == reality
    assert perfect["ship"] is True and perfect["verdict"] == "ship GNN"
    assert perfect["err_gnn_rmse"] == 0.0


def test_gnn_equal_to_sim_does_not_ship():
    tie = activation_gate(R_OBS, R_SIM, R_SIM, min_n=10)  # GNN == sim
    assert tie["ship"] is False and tie["verdict"] == "keep sim"
    assert tie["improvement_rmse"] == 0.0


def test_min_n_guard_blocks_ship():
    small = activation_gate(R_OBS[:5], R_OBS[:5], R_SIM[:5], min_n=10)  # better but too few
    assert small["ship"] is False


def test_eps_margin_required():
    # GNN only marginally better than sim → eps margin blocks the ship
    slightly = R_SIM + 1e-6
    res = activation_gate(R_OBS, slightly, R_SIM, eps=0.1, min_n=10)
    assert res["ship"] is False
