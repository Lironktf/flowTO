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
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.graph.routing import import_graph_json  # noqa: E402
from src.model.predict_node_demand import (  # noqa: E402
    load_demand_model, predict_node_demand,
)
from src.model.generate_od_matrix import generate_od_matrix  # noqa: E402
from src.simulation.simulate_traffic import (  # noqa: E402
    compare_simulations, simulate_scenario, simulate_traffic,
)
from src.simulation.export_results import export_baseline_result  # noqa: E402

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
    print(f"Predicted demand for {len(demand):,} nodes "
          f"(max {max(demand.values()):.0f} veh)")

    od = generate_od_matrix(graph, demand, TIME_CONTEXT, max_pairs=800)
    assert len(od) > 0, "no OD pairs generated"
    print(f"OD matrix: {len(od):,} pairs")

    result = simulate_traffic(graph, od, iterations=4, k_paths=3,
                              time_context=TIME_CONTEXT, node_demands=demand)
    s = result["summary"]

    assert s["total_assigned_trips"] > 0
    assert s["active_edges"] > 0
    assert 0.0 < s["average_pressure"] < 5.0
    assert len(result["frames"]) == 4

    export_baseline_result(result, BASELINE_OUT, od_sample=50, node_sample=200)
    assert os.path.exists(BASELINE_OUT)

    # ---- report -------------------------------------------------------
    print("\n=== BASELINE SUMMARY ===")
    print(f"  total assigned trips: {s['total_assigned_trips']:,.0f}")
    print(f"  active (loaded) edges: {s['active_edges']:,}")
    print(f"  average pressure:      {s['average_pressure']:.3f}")
    print(f"  high-risk edges:       {s['high_risk_edges']:,}")
    print(f"  severe edges:          {s['severe_edges']:,}")

    G = result["graph"]
    ranked = sorted(
        (d for _, _, d in G.edges(data=True) if d.get("status") != "closed"),
        key=lambda d: -(d.get("pressure") or 0),
    )[:10]
    print("\n  top 10 highest-pressure edges:")
    for d in ranked:
        print(f"    {str(d.get('road_name'))[:34]:34} "
              f"load={d.get('load',0):8.0f} cap={d.get('capacity',0):7.0f} "
              f"P={d.get('pressure',0):5.2f} {d.get('risk')}")

    # ---- scenario: close the single most-congested edge ---------------
    worst = ranked[0]
    worst_id = worst.get("edge_id")
    print(f"\n=== SCENARIO: close busiest edge {worst_id} "
          f"({worst.get('road_name')}) ===")
    scenario = [{"op": "close_edge", "edge_id": worst_id}]
    scen = simulate_scenario(graph, result["od_matrix"], scenario,
                             iterations=4, k_paths=3)
    impact = compare_simulations(result, scen)
    sd = impact["summary_delta"]
    print(f"  avg pressure delta: {sd['average_pressure']:+.4f}")
    print(f"  high-risk delta:    {sd['high_risk_edges']:+d}")
    print(f"  severe delta:       {sd['severe_edges']:+d}")
    print("  top rerouted edges (by load change):")
    for c in impact["most_impacted_edges"][:5]:
        print(f"    {str(c['road_name'])[:30]:30} "
              f"load {c['load_before']:8.0f} -> {c['load_after']:8.0f} "
              f"({c['load_delta']:+.0f})")

    # The closed edge must carry no load in the scenario.
    closed_after = next((c for c in impact["most_impacted_edges"]
                         if c["edge_id"] == worst_id), None)
    if closed_after is not None:
        assert closed_after["load_after"] == 0, "closed edge still loaded"

    print("\nPASS: demand + OD + assignment + propagation + scenario all work.")


if __name__ == "__main__":
    test_simulation()
