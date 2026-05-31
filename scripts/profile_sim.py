"""Profile a single scipy-backend equilibrium simulate_traffic call.

Builds graph/demand/OD once (not profiled), then cProfiles ONLY the
simulate_traffic call so we see where the routing/propagation time goes.
"""
from __future__ import annotations

import cProfile
import os
import pstats
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from torontosim.graph.routing import import_graph_json
from torontosim.model.odme_calibrate import build_grounded_od
from torontosim.model.predict_node_demand import load_demand_model, predict_node_demand
from torontosim.simulation.simulate_traffic import simulate_traffic

GRAPH_JSON = os.path.join(_ROOT, "data", "graph", "toronto_drive_graph.json")
TC = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}


def build():
    t = {}
    t0 = time.perf_counter(); graph = import_graph_json(GRAPH_JSON); t["graph_load"] = time.perf_counter() - t0
    t0 = time.perf_counter(); model = load_demand_model(); t["model_load"] = time.perf_counter() - t0
    t0 = time.perf_counter(); demand = predict_node_demand(graph, model, TC); t["demand_predict"] = time.perf_counter() - t0
    t0 = time.perf_counter(); grounded = build_grounded_od(graph, demand, TC, max_pairs=3000); t["od_build"] = time.perf_counter() - t0
    return graph, grounded["od"], demand, t


def main():
    graph, od, demand, t = build()
    print("=== setup phase timings (not the sim itself) ===")
    for k, v in t.items():
        print(f"  {k:16} {v:7.2f}s")
    print(f"  {'edges':16} {graph.number_of_edges():,}  od_pairs {len(od):,}\n")

    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    simulate_traffic(
        graph, od, iterations=4, k_paths=3, time_context=TC, node_demands=demand,
        engine="equilibrium", backend="scipy", congestion_model="bpr",
        rgap_target=1e-2, max_equilibrium_iter=30, auto_calibrate=False,
    )
    pr.disable()
    dt = time.perf_counter() - t0
    print(f"=== simulate_traffic (scipy/equilibrium): {dt:.2f}s ===\n")

    st = pstats.Stats(pr).strip_dirs().sort_stats("cumulative")
    print("--- top 25 by CUMULATIVE time ---")
    st.print_stats(25)
    st.sort_stats("tottime")
    print("--- top 20 by SELF (tottime) time ---")
    st.print_stats(20)


if __name__ == "__main__":
    main()
