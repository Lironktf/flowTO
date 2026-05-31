"""
First end-to-end test of the demand + simulation layer (Part 9).

Flow:
  1. Load the existing Toronto road graph.
  2. Pick a time context (Fri 17:00, June, clear).
  3. Predict node demand (trained model, or heuristic fallback).
  4. Generate the OD matrix.
  5. Simulate 4 propagation iterations.
  6. Export baseline_result.json.
  7. Print total trips, top-10 pressure edges, high/severe counts, avg pressure.
  8. Bonus: run a road-closure scenario and show the impact diff.

Run:
    python -m tests.test_simulation
    pytest tests/test_simulation.py -s
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import time  # noqa: E402

import numpy as np  # noqa: E402

from torontosim.graph.routing import import_graph_json  # noqa: E402
from torontosim.model.generate_od_matrix import generate_od_matrix  # noqa: E402,F401
from torontosim.model.odme_calibrate import build_grounded_od  # noqa: E402
from torontosim.model.predict_node_demand import (  # noqa: E402
    load_demand_model,
    predict_node_demand,
)
from torontosim.simulation.backends import (  # noqa: E402
    available_backends,
    scipy_backend,
)
from torontosim.simulation.backends import (
    cpu as cpu_backend,
)
from torontosim.simulation.equilibrium import network_from_graph  # noqa: E402
from torontosim.simulation.export_results import export_baseline_result  # noqa: E402
from torontosim.simulation.simulate_traffic import (  # noqa: E402
    compare_simulations,
    simulate_scenario,
    simulate_traffic,
)


def _pressures(graph):
    """Sorted list of loaded-edge pressures (open edges with load > 0)."""
    return sorted(
        d["pressure"]
        for _, _, d in graph.edges(data=True)
        if d.get("status") != "closed"
        and isinstance(d.get("pressure"), (int, float))
        and (d.get("load") or 0) > 0
    )


def _pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def _validate_scipy_backend(graph, od):
    """Wire-in check for the scipy all-or-nothing backend (the ~25x CPU win).

    Builds the compact Network, loads the OD with the heap-Dijkstra (`cpu`) and
    the vectorized `scipy` backends under identical free-flow costs, and asserts
    the resulting link flows agree (tie-breaking on equal-cost paths permits a
    small divergence) while scipy is dramatically faster.
    """
    print("\n=== SCIPY BACKEND (vectorized csgraph.dijkstra) ===")
    print(f"  available backends: {available_backends()}")
    assert "scipy" in available_backends(), "scipy backend should always be available"

    net, node_index, _edge_keys = network_from_graph(graph)
    costs = np.where(net.cap > 0, net.t0, np.inf).astype(np.float64)

    # OD grouped by origin in Network index space.
    od_by_origin: dict = {}
    for entry in od:
        o = node_index.get(entry["origin"])
        d = node_index.get(entry["destination"])
        trips = float(entry.get("trips", 0.0))
        if o is not None and d is not None and trips > 0:
            od_by_origin.setdefault(o, []).append((d, trips))

    # Cap origins for the head-to-head: the cpu heap is ~58 ms/origin, so a
    # subset keeps this check fast while still exercising both backends.
    if len(od_by_origin) > 40:
        od_by_origin = {o: od_by_origin[o] for o in sorted(od_by_origin)[:40]}
    print(
        f"  comparing on {len(od_by_origin)} origins "
        f"({sum(len(v) for v in od_by_origin.values())} OD pairs)"
    )

    def _time(fn):
        fn()  # warm-up
        t = time.perf_counter()
        out = fn()
        return out, time.perf_counter() - t

    f_cpu, t_cpu = _time(lambda: cpu_backend.all_or_nothing(net, costs, od_by_origin))
    f_sp, t_sp = _time(lambda: scipy_backend.all_or_nothing(net, costs, od_by_origin))

    total = float(np.abs(f_cpu).sum()) or 1.0
    l1 = float(np.abs(f_cpu - f_sp).sum())
    rel = l1 / total
    speedup = t_cpu / t_sp if t_sp > 0 else float("inf")
    print(
        f"  cpu heap : {t_cpu * 1e3:8.1f} ms   scipy: {t_sp * 1e3:8.1f} ms "
        f"-> {speedup:.1f}x faster"
    )
    print(f"  flow agreement: L1 diff {rel * 100:.3f}% of total flow (tie-break)")
    assert rel < 0.05, f"scipy flow diverges {rel:.2%} from cpu (>5%)"
    assert speedup > 1.0, "scipy backend should be faster than the heap backend"


GRAPH_JSON = os.path.join(_REPO_ROOT, "data", "graph", "toronto_drive_graph.json")
BASELINE_OUT = os.path.join(_REPO_ROOT, "data", "simulation", "baseline_result.json")

TIME_CONTEXT = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}


def test_simulation():
    graph = import_graph_json(GRAPH_JSON)
    assert graph.number_of_edges() > 0

    model = load_demand_model()
    print(f"Demand model: {model.get('kind')}")

    demand = predict_node_demand(graph, model, TIME_CONTEXT)
    assert len(demand) > 0
    print(f"Predicted demand for {len(demand):,} nodes " f"(max {max(demand.values()):.0f} veh)")

    grounded = build_grounded_od(graph, demand, TIME_CONTEXT, max_pairs=3000)
    od = grounded["od"]
    assert len(od) > 0, "no OD pairs generated"
    print(
        f"OD matrix: {len(od):,} pairs | ODME-grounded to {grounded['n_sensors']:,} real "
        f"sensors -> {grounded['grounded_total']:,.0f} trips "
        f"(vs invented nominal {grounded['seed_total']:,.0f})"
    )

    # Equilibrium engine (capacity-aware: drivers avoid full roads) on the fast
    # scipy backend + BPR congestion. rgap 1e-2 / 30 iters keeps it demo-fast
    # while staying visually converged (tighten for offline analysis).
    # auto_calibrate OFF: the OD magnitude is already grounded in real counts via
    # ODME, so no invented scaling / target-pressure / correction factor.
    result = simulate_traffic(
        graph,
        od,
        iterations=4,
        k_paths=3,
        time_context=TIME_CONTEXT,
        node_demands=demand,
        engine="equilibrium",
        backend="scipy",
        congestion_model="bpr",
        rgap_target=1e-2,
        max_equilibrium_iter=30,
        auto_calibrate=False,
    )
    s = result["summary"]

    assert s["total_assigned_trips"] > 0
    assert s["active_edges"] > 0
    assert 0.0 < s["average_pressure"] < 5.0
    assert len(result["frames"]) == 4

    export_baseline_result(result, BASELINE_OUT, od_sample=50, node_sample=200)
    assert os.path.exists(BASELINE_OUT)

    # ---- report -------------------------------------------------------
    G = result["graph"]
    ps = _pressures(G)
    print(f"\n=== BASELINE SUMMARY (engine={result['engine']}, backend={result['backend']}) ===")
    if "rgap" in result:
        print(
            f"  equilibrium: rgap={result['rgap']:.2e} "
            f"iters={result.get('equilibrium_iterations')} converged={result.get('converged')}"
        )
    print(f"  total assigned trips: {s['total_assigned_trips']:,.0f}")
    print(f"  active (loaded) edges: {s['active_edges']:,}")
    print(f"  average pressure:      {s['average_pressure']:.3f}")
    print(
        f"  median / p95 / max P:  {_pct(ps, .5):.2f} / {_pct(ps, .95):.2f} / "
        f"{(ps[-1] if ps else 0):.2f}"
    )
    print(f"  high-risk edges:       {s['high_risk_edges']:,}")
    print(f"  severe edges:          {s['severe_edges']:,}")
    print(f"  stranded trips:        {s.get('stranded_trips', 0):,.0f} (no route in the network)")
    if result["engine"] == "equilibrium" and ps and ps[-1] > 3.0:
        print(
            f"  NOTE: max pressure {ps[-1]:.1f}× = genuine rush-hour oversaturation "
            f"(v/c>1); more OD pairs + ODME calibration would spread it further."
        )

    # ---- scipy backend wire-in check ----------------------------------
    _validate_scipy_backend(graph, od)

    ranked = sorted(
        (d for _, _, d in G.edges(data=True) if d.get("status") != "closed"),
        key=lambda d: -(d.get("pressure") or 0),
    )[:10]
    print("\n  top 10 highest-pressure edges:")
    for d in ranked:
        print(
            f"    {str(d.get('road_name'))[:34]:34} "
            f"load={d.get('load',0):8.0f} cap={d.get('capacity',0):7.0f} "
            f"P={d.get('pressure',0):5.2f} {d.get('risk')}"
        )

    # ---- scenario: close the single most-congested edge ---------------
    worst = ranked[0]
    worst_id = worst.get("edge_id")
    print(f"\n=== SCENARIO: close busiest edge {worst_id} " f"({worst.get('road_name')}) ===")
    scenario = [{"op": "close_edge", "edge_id": worst_id}]
    scen = simulate_scenario(
        graph,
        result["od_matrix"],
        scenario,
        iterations=4,
        k_paths=3,
        engine="equilibrium",
        backend="scipy",
        congestion_model="bpr",
        rgap_target=1e-2,
        max_equilibrium_iter=30,
    )
    impact = compare_simulations(result, scen)
    sd = impact["summary_delta"]
    print(f"  avg pressure delta: {sd['average_pressure']:+.4f}")
    print(f"  high-risk delta:    {sd['high_risk_edges']:+d}")
    print(f"  severe delta:       {sd['severe_edges']:+d}")
    print(
        f"  stranded trips:     {sd.get('stranded_trips', 0):+,.0f} "
        f"(extra trips left with no route by this closure — a cost)"
    )
    print("  top rerouted edges (by load change):")
    for c in impact["most_impacted_edges"][:5]:
        print(
            f"    {str(c['road_name'])[:30]:30} "
            f"load {c['load_before']:8.0f} -> {c['load_after']:8.0f} "
            f"({c['load_delta']:+.0f})"
        )

    # The closed edge must carry no load in the scenario.
    closed_after = next(
        (c for c in impact["most_impacted_edges"] if c["edge_id"] == worst_id), None
    )
    if closed_after is not None:
        assert closed_after["load_after"] == 0, "closed edge still loaded"

    print("\nPASS: demand + OD + assignment + propagation + scenario all work.")


if __name__ == "__main__":
    test_simulation()
