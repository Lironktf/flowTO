"""P04 T04.6 — determinism of the equilibrium engine (CPU).

Same inputs -> byte-identical link flows + rgap. Includes a constructed
equal-cost tie (two parallel shortest paths) to prove the AON tie-break makes
path loading deterministic.
"""

from __future__ import annotations

import os

import numpy as np

from torontosim.simulation.equilibrium import frank_wolfe
from torontosim.simulation.network import build_network
from torontosim.simulation.oracle import build_network_from_tntp, parse_tntp_trips

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "tntp", "SiouxFalls")


def test_siouxfalls_assignment_is_byte_identical():
    net = build_network_from_tntp(open(os.path.join(FIX, "SiouxFalls_net.tntp")).read())
    od = parse_tntp_trips(open(os.path.join(FIX, "SiouxFalls_trips.tntp")).read())
    a = frank_wolfe(net, od, algorithm="cfw", max_iter=300, rgap_target=1e-4)
    b = frank_wolfe(net, od, algorithm="cfw", max_iter=300, rgap_target=1e-4)
    assert np.array_equal(a.flow, b.flow)
    assert a.rgap == b.rgap
    assert a.iterations == b.iterations


def _diamond_with_tie():
    # 0 -> {1,2} -> 3, both branches equal cost: two equal shortest paths.
    #   links: 0:0->1, 1:0->2, 2:1->3, 3:2->3
    net = build_network(
        n_nodes=4,
        tail=[0, 0, 1, 2],
        head=[1, 2, 3, 3],
        t0=[1.0, 1.0, 1.0, 1.0],
        cap=[1000.0, 1000.0, 1000.0, 1000.0],
        alpha=[0.15, 0.15, 0.15, 0.15],
        beta=[4.0, 4.0, 4.0, 4.0],
        edge_ids=["a", "b", "c", "d"],
    )
    return net


def test_equal_cost_tie_aon_is_deterministic():
    """A single all-or-nothing loads an equal-cost tie down ONE fixed branch."""
    from torontosim.simulation.backends import all_or_nothing
    from torontosim.simulation.network import bpr_costs

    net = _diamond_with_tie()
    od_by_origin = {0: [(3, 100.0)]}
    cost = bpr_costs(net, np.zeros(net.n_links))
    aux1 = all_or_nothing(net, cost, od_by_origin)
    aux2 = all_or_nothing(net, cost, od_by_origin)
    assert np.array_equal(aux1, aux2)
    # All 100 go down exactly one of the two parallel branches (tie-break),
    # never split — AON is all-or-nothing.
    assert aux1[0] in (0.0, 100.0)
    assert aux1[0] + aux1[1] == 100.0


def test_equal_cost_equilibrium_is_deterministic():
    net = _diamond_with_tie()
    od = [(0, 3, 100.0)]
    a = frank_wolfe(net, od, algorithm="fw", max_iter=50, rgap_target=1e-6)
    b = frank_wolfe(net, od, algorithm="fw", max_iter=50, rgap_target=1e-6)
    # Byte-identical across runs, and demand conserved across the two branches.
    assert np.array_equal(a.flow, b.flow)
    assert abs((a.flow[0] + a.flow[1]) - 100.0) < 1e-6


def test_scipy_backend_matches_cpu_aon_on_siouxfalls():
    """The vectorized scipy all-or-nothing must agree with the heap-Dijkstra cpu
    backend on a real network. The full-graph end-to-end sim checks this parity
    at scale (heavy/nightly); this keeps it on the PR path, fast, on the
    committed SiouxFalls fixture (link flows agree exactly here; the <5% bound is
    for equal-cost tie-breaks that can diverge on larger graphs)."""
    from torontosim.simulation.backends import cpu as cpu_backend
    from torontosim.simulation.backends import scipy_backend
    from torontosim.simulation.equilibrium import _od_by_origin

    net = build_network_from_tntp(open(os.path.join(FIX, "SiouxFalls_net.tntp")).read())
    od = parse_tntp_trips(open(os.path.join(FIX, "SiouxFalls_trips.tntp")).read())
    od_by_origin = _od_by_origin(od)
    costs = np.where(net.cap > 0, net.t0, np.inf).astype(np.float64)

    f_cpu = cpu_backend.all_or_nothing(net, costs, od_by_origin)
    f_scipy = scipy_backend.all_or_nothing(net, costs, od_by_origin)

    total = float(np.abs(f_cpu).sum()) or 1.0
    rel = float(np.abs(f_cpu - f_scipy).sum()) / total
    assert rel < 0.05, f"scipy flow diverges {rel:.2%} from cpu (>5%)"
