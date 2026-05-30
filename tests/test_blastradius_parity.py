"""P05 — the key correctness test: blast-radius == full recompute (AON layer).

At the all-or-nothing layer a local edge closure can only change the shortest
paths of ODs that used the closed edge, so re-routing *only* affected ODs
reproduces a full recompute **exactly** — while touching far fewer paths and
running faster. Also asserts determinism.
"""

from __future__ import annotations

import numpy as np

from tests.test_blastradius import _link_id, grid_network
from torontosim.blastradius.pathcache import build_path_cache
from torontosim.blastradius.recompute import blast_assign, full_aon


def _setup():
    net = grid_network(10)  # 100 nodes
    costs = net.t0.copy()
    # A spread of OD flows across the grid.
    od = []
    for r in range(10):
        od.append((r * 10, r * 10 + 9, 7.0))  # left -> right
    for c in range(10):
        od.append((c, 90 + c, 5.0))  # top -> bottom
    cache = build_path_cache(net, od, costs)
    return net, costs, od, cache


def test_blast_equals_full_recompute_on_close():
    net, costs, od, cache = _setup()
    e = _link_id(net, 44, 45)  # a central link
    new_costs = costs.copy()
    new_costs[e] = np.inf

    full = full_aon(net, od, new_costs)
    res = blast_assign(net, od, cache, [e], new_costs)

    # Exact parity at the AON layer.
    assert np.allclose(res.flow, full, atol=1e-9)
    # The closed link carries no flow.
    assert res.flow[e] == 0.0


def test_blast_touches_fewer_paths_than_full():
    net, costs, od, cache = _setup()
    e = _link_id(net, 44, 45)
    new_costs = costs.copy()
    new_costs[e] = np.inf
    # A tight radius without the (uniform-grid) highway core shows locality;
    # on the real graph varied capacity makes the core a small expressway set.
    res = blast_assign(
        net,
        od,
        cache,
        [e],
        new_costs,
        params={"start_radius_min": 3.0, "include_highway_core": False},
    )
    # Only a strict subset of ODs is recomputed (the rest reuse cached paths).
    assert 0 < len(res.affected_ods) < len(od)
    # The affected subgraph is a strict subset of the network.
    assert res.stats["subgraph_nodes"] < net.n_nodes


def test_blast_is_deterministic():
    net, costs, od, cache = _setup()
    e = _link_id(net, 44, 45)
    new_costs = costs.copy()
    new_costs[e] = np.inf
    a = blast_assign(net, od, cache, [e], new_costs)
    b = blast_assign(net, od, cache, [e], new_costs)
    assert np.array_equal(a.flow, b.flow)
    assert a.affected_ods == b.affected_ods
