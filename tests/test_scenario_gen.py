"""P13 §B — scenario generator tests (stub sim; runs on the GB10)."""

from __future__ import annotations

import pandas as pd

from torontosim.feedback.scenario_gen import generate_pairs, sample_interventions


def _edges():
    return pd.DataFrame(
        {
            "edge_id": [f"e{i}" for i in range(6)],
            "road_class": ["motorway", "primary", "secondary", "residential", "service", "tertiary"],
        }
    )


def test_sample_is_deterministic_and_sized():
    a = sample_interventions(_edges(), n=4, seed=42)
    b = sample_interventions(_edges(), n=4, seed=42)
    assert len(a) == 4
    assert [x["edge_id"] for x in a] == [x["edge_id"] for x in b]  # deterministic
    assert all(x["sign"] in ("closure", "opening") for x in a)
    assert all(x["ops"] and "op" in x["ops"][0] for x in a)


def test_p_closure_extremes():
    closes = sample_interventions(_edges(), n=5, seed=1, p_closure=1.0)
    opens = sample_interventions(_edges(), n=5, seed=1, p_closure=0.0)
    assert all(x["sign"] == "closure" for x in closes)
    assert all(x["sign"] == "opening" for x in opens)
    assert all(x["ops"][0]["op"] in ("close_edge", "change_capacity") for x in closes)
    assert all(x["ops"][0].get("multiplier", 0) > 1 for x in opens)  # opening adds capacity


def test_sample_caps_at_edge_count():
    assert len(sample_interventions(_edges(), n=999, seed=0)) == 6


def test_generate_pairs_residual_over_open():
    interventions = [
        {"id": "sim0", "edge_id": "e1", "sign": "closure", "ops": [{"op": "close_edge", "edge_id": "e1"}]}
    ]
    sim_open = lambda: {"e1": 100.0, "e2": 50.0}
    sim_int = lambda ops: {"e1": 0.0, "e2": 140.0}  # close e1 → flow reroutes to e2
    df = generate_pairs(interventions, sim_open, sim_int).set_index("edge_id")
    assert df.loc["e1", "delta_flow"] == -100.0   # closed edge loses its flow
    assert df.loc["e2", "delta_flow"] == 90.0     # detour gains
    assert df.loc["e1", "closed_edge"] == "e1" and df.loc["e1", "sign"] == "closure"


def test_generate_pairs_empty_when_no_interventions():
    df = generate_pairs([], lambda: {"e1": 1.0}, lambda ops: {"e1": 1.0})
    assert df.empty
