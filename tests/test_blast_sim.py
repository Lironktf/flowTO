"""CPU tests for the blast-radius sim adapter (P13 perf, spec 15).

The blast modules run on CPU (no torch/GPU), so the open-vs-closed rerouting and its
parity with a full all-or-nothing recompute are checked locally on a tiny network.
"""

from __future__ import annotations

import networkx as nx

from torontosim.feedback.blast_sim import simulate_open_intervened_blast


def _diamond() -> nx.MultiDiGraph:
    """A→D via B (ab,bd) or C (ac,cd); the B route is the shorter default."""
    g = nx.MultiDiGraph()
    for n, (x, y) in {"A": (0, 0), "B": (1, 1), "C": (1, -1), "D": (2, 0)}.items():
        g.add_node(n, x=x, y=y)

    def add(u, v, eid, bt):
        g.add_edge(u, v, key=0, edge_id=eid, base_time_min=bt, capacity=100.0, road_class="primary")

    add("A", "B", "ab", 1.0)
    add("B", "D", "bd", 1.0)
    add("A", "C", "ac", 1.1)
    add("C", "D", "cd", 1.1)
    return g


def test_blast_open_then_closure_reroutes():
    g = _diamond()
    od = [{"origin": "A", "destination": "D", "trips": 100.0}]
    sim_open, sim_int = simulate_open_intervened_blast(g, od, backend="cpu")

    open_flow = sim_open()
    # all 100 trips take the shorter B route when open
    assert open_flow["ab"] == 100.0 and open_flow["bd"] == 100.0
    assert open_flow["ac"] == 0.0 and open_flow["cd"] == 0.0

    # closing ab forces the C route; edge-id keys match the sim's flow dict
    closed = sim_int([{"op": "close_edge", "edge_id": "ab"}])
    assert closed["ab"] == 0.0
    assert closed["ac"] == 100.0 and closed["cd"] == 100.0


def test_blast_no_op_returns_open():
    g = _diamond()
    od = [{"origin": "A", "destination": "D", "trips": 100.0}]
    sim_open, sim_int = simulate_open_intervened_blast(g, od, backend="cpu")
    # an op on an unknown edge changes nothing → identical to the open solve
    assert sim_int([{"op": "close_edge", "edge_id": "nope"}]) == sim_open()


def test_blast_matches_full_aon_on_residual_signs():
    """r_sim = closed − open has the expected sign at the rerouted edges."""
    g = _diamond()
    od = [{"origin": "A", "destination": "D", "trips": 100.0}]
    sim_open, sim_int = simulate_open_intervened_blast(g, od, backend="cpu")
    o = sim_open()
    c = sim_int([{"op": "close_edge", "edge_id": "ab"}])
    # detour edges gain flow, the closed corridor loses it
    assert c["ac"] - o["ac"] > 0
    assert c["ab"] - o["ab"] < 0


def test_generate_from_sim_blast_is_closures_only():
    """Blast scenario-gen yields closure pairs (no openings) with a real reroute."""
    from torontosim.feedback.scenario_gen import generate_from_sim

    g = _diamond()
    od = [{"origin": "A", "destination": "D", "trips": 100.0}]
    pairs = generate_from_sim(g, od, n=2, seed=0, solver="blast", backend="cpu")
    assert not pairs.empty
    assert set(pairs["sign"].unique()) <= {"closure"}      # no openings under blast
    # at least one scenario actually moves flow (sim_int != sim_open somewhere)
    assert (pairs["delta_flow"].abs() > 1e-9).any()
