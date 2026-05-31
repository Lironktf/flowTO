"""Torch-free tests for the Stage-2 fine-tune helpers.

The trainer itself runs torch on the GB10; here we cover the pieces that are pure
Python/NumPy: the held-out split selection and the per-closure channel/target
construction (``scenario_edge_channels`` used with the global sim_open + masked
real targets), which is exactly what ``build_stage2_tensors`` does per scenario.
"""

from __future__ import annotations

import numpy as np

from torontosim.feedback.dataset import scenario_edge_channels
from torontosim.feedback.train_residual import _split_indices


def test_split_indices_holds_out_only_test():
    splits = ["train", "test", "train", "test", None]
    train, test = _split_indices(splits)
    assert train == [0, 2, 4]  # missing split never leaks into held-out
    assert test == [1, 3]


def test_split_indices_no_test_fold():
    train, test = _split_indices(["train", "train"])
    assert test == []
    assert train == [0, 1]


def test_stage2_channels_fill_global_simopen_and_mask_targets():
    # one closure: closed edge e1, observed real residual only at e2
    edge_order = ["e1", "e2", "e3"]
    capacity = {"e1": 100.0, "e2": 50.0, "e3": 200.0}
    sim_open_full = {"e1": 80.0, "e2": 40.0, "e3": 10.0}
    closed = "e1"
    robs = {"e2": 30.0}  # r_obs (flow) at the observed site

    # mirror build_stage2_tensors' per-scenario scn construction
    scn = {
        e: ("closure", closed, float(sim_open_full.get(e, 0.0)), robs.get(e, 0.0))
        for e in edge_order
    }
    chan, tgt = scenario_edge_channels(scn, edge_order, capacity)
    obs_mask = np.array([1.0 if e in robs else 0.0 for e in edge_order])

    mask, cmult, so_load, so_press = chan.T
    # intervention channel: closed edge masked + capacity zeroed; others untouched
    assert mask.tolist() == [1.0, 0.0, 0.0]
    assert cmult.tolist() == [0.0, 1.0, 1.0]
    # sim_open load filled for ALL edges from the global solve
    assert so_load.tolist() == [80.0, 40.0, 10.0]
    assert so_press[1] == 40.0 / 50.0
    # target is the real Δpressure ONLY at the observed edge; zero (masked) elsewhere
    assert tgt[1] == 30.0 / 50.0
    assert tgt[0] == 0.0 and tgt[2] == 0.0
    assert obs_mask.tolist() == [0.0, 1.0, 0.0]
    # flow units recover exactly: tgt * cap == r_obs at the observed edge
    assert tgt[1] * capacity["e2"] == 30.0
