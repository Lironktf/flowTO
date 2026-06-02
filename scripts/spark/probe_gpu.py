"""One-off: is the GPU (cuGraph) assignment actually faster than CPU here?

Times a realistic kpath assignment on both backends. Run on the Spark:
    scripts/spark/run.sh "python scripts/spark/probe_gpu.py"
"""

import time

from torontosim.graph.routing import import_graph_json
from torontosim.model.generate_od_matrix import generate_od_matrix
from torontosim.model.predict_node_demand import load_demand_model, predict_node_demand
from torontosim.simulation.assign_paths import assign_demand_to_paths

g = import_graph_json("data/graph/toronto_drive_graph.json")
for _u, _v, d in g.edges(data=True):
    d["current_time_min"] = d.get("base_time_min") or 1.0

tc = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}
dem = predict_node_demand(g, load_demand_model(), tc)
od = generate_od_matrix(g, dem, tc, max_pairs=2000)
n_origins = len({o["origin"] for o in od})
print(f"graph {g.number_of_edges()} edges | {len(od)} OD pairs | {n_origins} distinct origins")


def run(backend):
    # warm/JIT once for gpu (CUDA context), then time a second pass
    if backend == "gpu":
        assign_demand_to_paths(g, od, k=3, reset=True, backend="gpu")
    t0 = time.time()
    assign_demand_to_paths(g, od, k=3, reset=True, backend=backend)
    dt = time.time() - t0
    loaded = sum(1 for _u, _v, d in g.edges(data=True) if (d.get("load") or 0) > 0)
    print(f"  {backend:4s}: {dt:6.2f}s  ({loaded} edges loaded)")
    return dt


cpu = run("cpu")
gpu = run("gpu")
print(f"\nspeedup gpu vs cpu: {cpu/gpu:.2f}x" if gpu > 0 else "n/a")
