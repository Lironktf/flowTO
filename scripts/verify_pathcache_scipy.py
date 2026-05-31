"""Verify build_path_cache(backend='scipy') vs the CPU heap version.

Shortest paths aren't unique, so we don't require identical link lists — we
require identical *path cost* per OD (a true shortest path) and identical
reachability, then time the two. Also exercises the ODME _node_paths consumer.
"""
from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np

from torontosim.blastradius.pathcache import build_path_cache
from torontosim.graph.routing import import_graph_json
from torontosim.model.odme_calibrate import build_grounded_od
from torontosim.model.predict_node_demand import load_demand_model, predict_node_demand
from torontosim.simulation.equilibrium import network_from_graph

GRAPH_JSON = os.path.join(_ROOT, "data", "graph", "toronto_drive_graph.json")
TC = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}


def path_cost(net, costs, link_path):
    return float(sum(costs[li] for li in link_path)) if link_path else np.inf


def main():
    graph = import_graph_json(GRAPH_JSON)
    model = load_demand_model()
    demand = predict_node_demand(graph, model, TC)
    od_pairs = build_grounded_od(graph, demand, TC, max_pairs=3000)["od"]

    net, node_index, _ = network_from_graph(graph)
    costs = np.where(net.cap > 0, net.t0, np.inf).astype(np.float64)
    odl = [
        (node_index[e["origin"]], node_index[e["destination"]], 1.0)
        for e in od_pairs
        if e["origin"] in node_index and e["destination"] in node_index
    ]

    t0 = time.perf_counter(); cpu = build_path_cache(net, odl, costs, backend="cpu"); t_cpu = time.perf_counter() - t0
    t0 = time.perf_counter(); sp = build_path_cache(net, odl, costs, backend="scipy"); t_sp = time.perf_counter() - t0

    # Compare path COST (not exact links) — shortest paths can tie.
    bad_cost = bad_reach = 0
    max_cost_diff = 0.0
    for cp, spp in zip(cpu.paths, sp.paths):
        if bool(cp) != bool(spp):
            bad_reach += 1
            continue
        cc, sc = path_cost(net, costs, cp), path_cost(net, costs, spp)
        d = abs(cc - sc)
        max_cost_diff = max(max_cost_diff, d)
        # tolerate the tie-break epsilon accumulated along the path
        if d > 1e-3 * max(cc, 1.0):
            bad_cost += 1

    print(f"OD pairs: {len(odl):,}")
    print(f"cpu  build: {t_cpu:6.2f}s")
    print(f"scipy build: {t_sp:6.2f}s   -> {t_cpu/max(t_sp,1e-9):.0f}x faster")
    print(f"reachability mismatches: {bad_reach}")
    print(f"cost mismatches (>0.1%): {bad_cost}   max |cost diff| = {max_cost_diff:.4g}")

    ok = bad_reach == 0 and bad_cost == 0
    print("\nRESULT:", "PASS — scipy paths are equal-cost shortest paths" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
