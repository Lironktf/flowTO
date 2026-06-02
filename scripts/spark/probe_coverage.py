"""One-off: validate citywide OD coverage + GPU backend on the GB10.

Run on the Spark via:  scripts/spark/run.sh "python scripts/spark/probe_coverage.py"

Loads the real graph + the real (xgboost) demand model, builds the 12k-pair
citywide OD, runs the baseline demo scenario on the requested backend, and
reports wall-time + how much of the map actually carries flow.
"""

import os
import time

from torontosim.demo import wc_surge
from torontosim.graph.routing import import_graph_json
from torontosim.model.generate_od_matrix import generate_od_matrix
from torontosim.model.predict_node_demand import load_demand_model, predict_node_demand

BACKEND = os.environ.get("TS_BACKEND", "gpu")
MAX_PAIRS = int(os.environ.get("TS_MAX_PAIRS", "12000"))

g = import_graph_json("data/graph/toronto_drive_graph.json")
NE = g.number_of_edges()
print(f"graph: {g.number_of_nodes():,} nodes  {NE:,} edges")

model = load_demand_model()
print(f"demand model: {model.get('kind')}")  # expect a trained xgboost payload, not Heuristic
tc = wc_surge.TIME_CONTEXT
dem = predict_node_demand(g, model, tc)

t0 = time.time()
od = generate_od_matrix(g, dem, tc, max_pairs=MAX_PAIRS)
print(f"OD: {len(od):,} pairs in {time.time()-t0:.1f}s")

t0 = time.time()
res = wc_surge.run_scenario("baseline", graph=g, baseline_od=od, backend=BACKEND)
dt = time.time() - t0

rg = res["graph"]
loaded = [d for _u, _v, d in rg.edges(data=True) if (d.get("load") or 0) > 0]
pressures = [d.get("pressure") or 0 for d in loaded]
lats = [g.nodes[u]["y"] for u, _v, d in rg.edges(data=True) if (d.get("load") or 0) > 0]
lons = [g.nodes[u]["x"] for u, _v, d in rg.edges(data=True) if (d.get("load") or 0) > 0]
print(f"\nbaseline on backend={BACKEND}: {dt:.1f}s")
print(f"  loaded edges: {len(loaded):,} = {100*len(loaded)/NE:.1f}% of the map")
if pressures:
    pressures.sort()
    p = lambda q: pressures[min(len(pressures) - 1, int(q * len(pressures)))]
    print(f"  pressure  median={p(.5):.2f}  p90={p(.9):.2f}  max={pressures[-1]:.2f}")
if lats:
    print(f"  geo span  {(max(lats)-min(lats))*111:.0f} x {(max(lons)-min(lons))*85:.0f} km")
print(f"  exhibition_pressure={res['exhibition_pressure']}  headline={res['headline_metric']}")
