"""P14 Phase 6 — sim-counterfactual residual tests (stub sim; runs anywhere)."""

from __future__ import annotations

from torontosim.feedback.groundtruth.counterfactual import compute_residuals


def _sim_open():
    return {"e1": 100.0, "e2": 50.0}  # equilibrium with the road open


def _sim_intervened(ops):
    # closing e1 reroutes flow: e1 drops, e2 rises
    return {"e1": 60.0, "e2": 90.0}


def test_residuals_signed_and_referenced_to_sim_open():
    interventions = [{"ID": "r1", "ops": [{"op": "close_edge", "edge_id": "e1"}]}]
    observed = {("r1", "e1"): 70.0, ("r1", "e2"): 85.0}
    df = compute_residuals(interventions, observed, _sim_open, _sim_intervened).set_index("edge_id")

    e1 = df.loc["e1"]
    assert e1["sim_open"] == 100.0 and e1["sim_int"] == 60.0
    assert e1["r_sim"] == -40.0  # 60 - 100 (sim's predicted drop)
    assert e1["r_obs"] == -30.0  # 70 - 100 (real drop, smaller than sim predicted)

    e2 = df.loc["e2"]
    assert e2["r_sim"] == 40.0  # 90 - 50
    assert e2["r_obs"] == 35.0  # 85 - 50


def test_no_residual_without_observed_or_sim_baseline():
    interventions = [{"ID": "r1", "ops": []}]
    # e3 has an observed count but no sim_open entry → no fabricated row
    observed = {("r1", "e3"): 10.0}
    df = compute_residuals(interventions, observed, _sim_open, _sim_intervened)
    assert df.empty


def test_unaffected_link_has_zero_sim_residual():
    # an intervention that changes nothing → r_sim == 0, r_obs reflects reality
    interventions = [{"ID": "r1", "ops": []}]
    observed = {("r1", "e1"): 100.0}
    df = compute_residuals(interventions, observed, _sim_open, lambda ops: _sim_open()).set_index(
        "edge_id"
    )
    assert df.loc["e1", "r_sim"] == 0.0
    assert df.loc["e1", "r_obs"] == 0.0
