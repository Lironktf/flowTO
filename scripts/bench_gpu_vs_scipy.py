"""Head-to-head: simulate_traffic on the cuGraph GPU backend vs the SciPy backend.

Builds the graph/demand/OD exactly like tests/test_simulation.py, then runs the
SAME equilibrium simulation twice — once backend="gpu", once backend="scipy" —
and compares wall-clock time and result agreement. Confirms cuGraph actually
executes (not just that it imports).
"""
from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from torontosim.graph.routing import import_graph_json
from torontosim.model.odme_calibrate import build_grounded_od
from torontosim.model.predict_node_demand import load_demand_model, predict_node_demand
from torontosim.simulation.backends import available_backends
from torontosim.simulation.simulate_traffic import simulate_traffic

GRAPH_JSON = os.path.join(_ROOT, "data", "graph", "toronto_drive_graph.json")
TIME_CONTEXT = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}


def run(graph, od, demand, backend):
    t0 = time.perf_counter()
    result = simulate_traffic(
        graph,
        od,
        iterations=4,
        k_paths=3,
        time_context=TIME_CONTEXT,
        node_demands=demand,
        engine="equilibrium",
        backend=backend,
        congestion_model="bpr",
        rgap_target=1e-2,
        max_equilibrium_iter=30,
        auto_calibrate=False,
    )
    dt = time.perf_counter() - t0
    return result, dt


def main():
    print(f"available backends: {available_backends()}")
    print("building graph / demand / OD (shared by both runs)...")
    graph = import_graph_json(GRAPH_JSON)
    model = load_demand_model()
    demand = predict_node_demand(graph, model, TIME_CONTEXT)
    grounded = build_grounded_od(graph, demand, TIME_CONTEXT, max_pairs=3000)
    od = grounded["od"]
    print(f"  {graph.number_of_edges():,} edges | {len(od):,} OD pairs\n")

    out = {}
    for backend in ("scipy", "gpu"):
        if backend not in available_backends():
            print(f"[{backend}] NOT available — skipping")
            continue
        print(f"[{backend}] running equilibrium simulation...")
        result, dt = run(graph, od, demand, backend)
        s = result["summary"]
        out[backend] = (result, dt)
        print(f"[{backend}] {dt:.2f}s  | engine={result['engine']} backend={result['backend']} "
              f"| trips={s['total_assigned_trips']:,.0f} avg_P={s['average_pressure']:.4f} "
              f"active={s['active_edges']:,} severe={s.get('severe_edges','?')}\n")

    if "scipy" in out and "gpu" in out:
        ts, tg = out["scipy"][1], out["gpu"][1]
        ss, sg = out["scipy"][0]["summary"], out["gpu"][0]["summary"]
        print("=" * 56)
        print(f"scipy: {ts:.2f}s   gpu(cuGraph): {tg:.2f}s   -> "
              f"{'scipy' if ts < tg else 'gpu'} faster by {max(ts,tg)/min(ts,tg):.2f}x")
        dp = abs(ss["average_pressure"] - sg["average_pressure"])
        print(f"avg-pressure agreement: scipy={ss['average_pressure']:.4f} "
              f"gpu={sg['average_pressure']:.4f}  |delta|={dp:.4f}")


if __name__ == "__main__":
    main()
