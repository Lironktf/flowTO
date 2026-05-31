"""Fast blast-radius sim adapter for the Stage-2 residual solves (P13 perf, spec 15).

The slow part of Stage-2 is re-solving the whole ~94k-edge equilibrium **open vs closed**
for every real closure. A single closure only perturbs traffic locally, so this adapter
builds the open network + shortest-path cache **once** and, for each closure, re-routes
**only the affected OD bundles** via ``blastradius.recompute.blast_assign`` instead of a
full re-solve. It returns the same ``(simulate_open, simulate_intervened)`` interface as
``groundtruth.counterfactual.simulate_open_intervened``, so ``build_real_residuals`` can
swap it in with ``solver="blast"``.

**Fidelity:** loading is all-or-nothing over the affected subgraph — it drops the full BPR
congestion-equilibrium feedback the full solver has. That is the intended speed/quality
trade. Both legs (open and intervened) use this same method here, so ``r_sim = sim_int −
sim_open`` and ``r_obs = observed − sim_open`` stay internally consistent. Use the full
solver as the parity oracle. Handles **closures** (``close_edge`` / capacity→0); partial
capacity cuts and openings need the congestion feedback → fall back to the full solver.
See ``docs/specs/15-feedback-loop-perf.md``.
"""

from __future__ import annotations

import numpy as np


def _edge_key(edge_id, uvk) -> str:
    """Match ``counterfactual._flows``' key: ``edge_id`` or ``f"{u}-{v}-{k}"``."""
    u, v, k = uvk
    return str(edge_id if edge_id is not None else f"{u}-{v}-{k}")


def simulate_open_intervened_blast(  # pragma: no cover - exercised by tests via tiny graph
    graph, od_matrix, *, backend: str = "cpu", **_ignored
):
    """Build (open, intervened) callbacks over the blast-radius recompute.

    Drop-in for ``counterfactual.simulate_open_intervened`` (extra kwargs like
    ``max_iter``/``rgap`` are accepted and ignored — blast has no Frank–Wolfe loop).
    The open network + path cache are built once and shared across all closures.
    """
    from torontosim.blastradius.pathcache import build_path_cache
    from torontosim.blastradius.recompute import aon_flow, blast_assign
    from torontosim.simulation.equilibrium import network_from_graph

    net, node_index, edge_keys = network_from_graph(graph)
    od = [
        (node_index[e["origin"]], node_index[e["destination"]], float(e.get("trips", 0.0)))
        for e in od_matrix
        if e["origin"] in node_index and e["destination"] in node_index and e.get("trips", 0) > 0
    ]
    base_costs = net.t0.copy()
    cache = build_path_cache(net, od, base_costs, backend=backend)

    keys = [_edge_key(net.edge_ids[i], edge_keys[i]) for i in range(len(edge_keys))]
    # edge_id (and the composite fallback) → link index
    id_to_idx: dict = {}
    for i, eid in enumerate(net.edge_ids):
        if eid is not None:
            id_to_idx.setdefault(str(eid), i)
    for i, k in enumerate(keys):
        id_to_idx.setdefault(k, i)

    open_flow = aon_flow(net, od, cache.paths)
    open_dict = {keys[i]: float(open_flow[i]) for i in range(len(keys))}

    def simulate_open():
        return open_dict

    def simulate_intervened(ops):
        changed = []
        new_costs = base_costs.copy()
        for op in ops or []:
            i = id_to_idx.get(str(op.get("edge_id")))
            if i is None:
                continue
            name = op.get("op")
            if name == "close_edge" or (name == "change_capacity" and op.get("multiplier", 0.0) <= 0):
                new_costs[i] = np.inf
                changed.append(i)
            # partial capacity / openings need congestion feedback → full solver only
        if not changed:
            return open_dict
        res = blast_assign(net, od, cache, changed, new_costs, backend=backend)
        return {keys[i]: float(res.flow[i]) for i in range(len(keys))}

    return simulate_open, simulate_intervened
