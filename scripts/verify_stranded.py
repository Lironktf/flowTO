"""Verify the new vectorized _count_stranded_trips == old path-cache version.

Checks equality on the baseline AND on a closure scenario (where stranded can be
> 0 because a closed edge can disconnect destinations), and times both.
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

from torontosim.graph.routing import import_graph_json
from torontosim.model.odme_calibrate import build_grounded_od
from torontosim.model.predict_node_demand import load_demand_model, predict_node_demand
from torontosim.simulation import simulate_traffic as st

GRAPH_JSON = os.path.join(_ROOT, "data", "graph", "toronto_drive_graph.json")
TC = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}


def old_count(graph, od_matrix) -> float:
    """The previous implementation, verbatim, for the equality check."""
    from torontosim.blastradius.pathcache import build_path_cache
    from torontosim.simulation.equilibrium import network_from_graph

    net, node_index, _ = network_from_graph(graph)
    costs = np.where(net.cap > 0, net.t0, np.inf).astype(np.float64)
    od = [
        (node_index[e["origin"]], node_index[e["destination"]], float(e.get("trips", 0.0)))
        for e in od_matrix
        if e["origin"] in node_index and e["destination"] in node_index and e.get("trips", 0) > 0
    ]
    if not od:
        return 0.0
    cache = build_path_cache(net, od, costs, backend="scipy")
    return float(sum(d for (_o, _d, d), path in zip(od, cache.paths) if not path))


def time_it(fn, *a):
    t0 = time.perf_counter()
    v = fn(*a)
    return v, time.perf_counter() - t0


def main():
    graph = import_graph_json(GRAPH_JSON)
    model = load_demand_model()
    demand = predict_node_demand(graph, model, TC)
    od = build_grounded_od(graph, demand, TC, max_pairs=3000)["od"]

    cases = [("baseline", graph)]

    # Scenario: close the busiest few edges to try to strand some trips.
    g2 = graph.copy()
    busiest = sorted(g2.edges(keys=True, data=True),
                     key=lambda e: -(e[3].get("capacity") or 0))[:50]
    for u, v, k, _d in busiest:
        g2[u][v][k]["capacity"] = 0.0
        g2[u][v][k]["status"] = "closed"
    cases.append(("50-edge-closure", g2))

    # Force a genuinely stranded trip: fully isolate one OD destination by
    # closing every edge incident to it, so its trips become unreachable.
    g3 = graph.copy()
    dest = od[0]["destination"]
    for u, v, k in list(g3.edges(keys=True)):
        if u == dest or v == dest:
            g3[u][v][k]["capacity"] = 0.0
            g3[u][v][k]["status"] = "closed"
    cases.append(("isolated-dest", g3))

    ok = True
    for name, g in cases:
        old, t_old = time_it(old_count, g, od)
        new, t_new = time_it(st._count_stranded_trips, g, od)
        match = abs(old - new) < 1e-6
        ok = ok and match
        print(f"[{name:16}] old={old:,.1f} ({t_old:6.2f}s)  "
              f"new={new:,.1f} ({t_new:6.3f}s)  "
              f"{'MATCH' if match else 'MISMATCH'}  speedup={t_old/max(t_new,1e-9):.0f}x")

    print("\nRESULT:", "PASS — identical counts" if ok else "FAIL — counts differ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
