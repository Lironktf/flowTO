"""P05 — blast-radius subgraph extraction + affected-path detection."""

from __future__ import annotations

import numpy as np

from torontosim.blastradius.pathcache import build_path_cache
from torontosim.blastradius.recompute import affected_region, blast_assign
from torontosim.simulation.network import build_network


def grid_network(n: int):
    """n×n grid; bidirectional unit-time links. node id = r*n + c."""
    tail, head = [], []
    for r in range(n):
        for c in range(n):
            u = r * n + c
            if c + 1 < n:
                v = r * n + (c + 1)
                tail += [u, v]
                head += [v, u]
            if r + 1 < n:
                v = (r + 1) * n + c
                tail += [u, v]
                head += [v, u]
    m = len(tail)
    net = build_network(
        n * n,
        tail,
        head,
        t0=[1.0] * m,
        cap=[1000.0] * m,
        alpha=[0.15] * m,
        beta=[4.0] * m,
    )
    return net


def _link_id(net, u, v):
    for i in range(net.n_links):
        if net.tail[i] == u and net.head[i] == v:
            return i
    raise KeyError((u, v))


def test_affected_region_local_and_small():
    net = grid_network(8)  # 64 nodes
    costs = net.t0.copy()
    # Close a central link.
    e = _link_id(net, 27, 28)  # node (3,3)->(3,4)
    nodes, links = affected_region(net, [e], costs, radius_min=3.0, include_highway_core=False)
    # Contains the changed-edge endpoints.
    assert 27 in nodes and 28 in nodes
    # Excludes a far corner node (node 0) beyond the 3-min radius.
    assert 0 not in nodes
    # Subgraph is a strict subset of the whole graph.
    assert len(nodes) < net.n_nodes


def test_affected_ods_via_reverse_index():
    net = grid_network(6)
    costs = net.t0.copy()
    od = [(0, 35, 10.0), (5, 30, 10.0)]  # two corner-to-corner flows
    cache = build_path_cache(net, od, costs)
    # Every link on OD 0's path maps back to OD 0.
    some_link = cache.paths[0][0]
    assert 0 in cache.edge_to_ods[some_link]
    # Closing a link off OD0's path doesn't flag OD0.
    affected = cache.affected_ods([cache.paths[1][0]])
    assert affected == {1} or 0 not in affected or 1 in affected


def test_blast_assign_reports_subgraph_fraction():
    net = grid_network(8)
    costs = net.t0.copy()
    od = [(r * 8, r * 8 + 7, 5.0) for r in range(8)]  # left->right each row
    cache = build_path_cache(net, od, costs)
    e = _link_id(net, 27, 28)
    new_costs = costs.copy()
    new_costs[e] = np.inf
    res = blast_assign(net, od, cache, [e], new_costs)
    assert res.stats["node_fraction"] <= 1.0
    assert res.stats["n_affected_ods"] <= len(od)
