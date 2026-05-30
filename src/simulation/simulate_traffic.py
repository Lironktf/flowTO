"""
The propagation loop — the heart of the simulation.

    simulate_traffic(graph, od_matrix, iterations=4, k_paths=3) -> result

Each iteration:
  1. zero edge loads
  2. assign OD trips to the top-k paths using *current* (congested) edge times
  3. recompute pressure / travel time / risk for every edge
  4. snapshot the edge states (a "frame" for animation)

Because step 2 routes on the times produced by step 3 of the previous
iteration, congestion propagates: a road that overloaded last round is slower
this round, so some drivers shift to alternates — which may then congest too.
The final iteration is the stabilised baseline.

Scenario simulation reuses the exact same machinery: mutate the graph (close /
add / remove / re-capacity an edge), then run `simulate_traffic` again on the
*same* OD matrix and `compare_simulations` the two results.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from .assign_paths import assign_demand_to_paths
from .congestion import reset_loads, update_edge_congestion

INF = float("inf")

# Auto-calibration target: scale total trips so the median loaded edge sits near
# this pressure. Keeps output plausible regardless of raw demand magnitudes.
DEFAULT_TARGET_PRESSURE = 0.55


def _loaded_pressures(graph):
    out = []
    for _, _, d in graph.edges(data=True):
        if d.get("status") == "closed":
            continue
        load = d.get("load", 0.0) or 0.0
        cap = d.get("capacity", 0.0) or 0.0
        if load > 0 and cap > 0:
            p = d.get("pressure")
            if p is not None and math.isfinite(p):
                out.append(p)
    return out


def _calibrate_trips(graph, od_matrix, k_paths, weather, target_pressure):
    """Return an OD list scaled so the mean loaded-edge pressure ≈ target.

    Pressure is linear in trips for a fixed routing pattern, so one assignment
    pass tells us the scale factor. Non-destructive: resets the graph after.
    """
    reset_loads(graph)
    assign_demand_to_paths(graph, od_matrix, k=k_paths, reset=True)
    update_edge_congestion(graph, weather=weather)
    pressures = _loaded_pressures(graph)
    reset_loads(graph)
    if not pressures:
        return [dict(od) for od in od_matrix], 1.0
    mean_p = sum(pressures) / len(pressures)
    scale = (target_pressure / mean_p) if mean_p > 0 else 1.0
    scale = max(0.01, min(100.0, scale))
    scaled = [{**od, "trips": od["trips"] * scale} for od in od_matrix]
    return scaled, scale


def _frame(graph, step, label, only_active=True):
    """Compact per-iteration snapshot of edge states for animation."""
    states = []
    for u, v, d in graph.edges(data=True):
        load = d.get("load", 0.0) or 0.0
        if only_active and load <= 0 and d.get("status") != "closed":
            continue
        states.append({
            "edge_id": d.get("edge_id"),
            "load": round(load, 1),
            "pressure": _num(d.get("pressure")),
            "current_time_min": _num(d.get("current_time_min")),
            "risk": d.get("risk", "low"),
        })
    return {"step": step, "label": label, "edge_states": states}


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return "Infinity" if math.isinf(f) else round(f, 4)


_LABELS = ["initial assignment", "first congestion update",
           "secondary rerouting", "stabilized baseline"]


def _label_for(step, iterations):
    if step == iterations - 1:
        return "stabilized baseline"
    if step < len(_LABELS):
        return _LABELS[step]
    return f"rerouting pass {step}"


def simulate_traffic(
    graph,
    od_matrix: List[dict],
    iterations: int = 4,
    k_paths: int = 3,
    weather: Optional[str] = None,
    time_context: Optional[dict] = None,
    node_demands: Optional[Dict[object, float]] = None,
    auto_calibrate: bool = True,
    target_pressure: float = DEFAULT_TARGET_PRESSURE,
    capture_frames: bool = True,
    copy_graph: bool = True,
) -> dict:
    """Run the propagation loop and return a simulation result dict.

    The input graph is copied by default so the caller's graph is untouched
    (set copy_graph=False to mutate in place). The returned `od_matrix` is the
    (possibly calibrated) one actually used — pass it to `simulate_scenario` so
    the scenario is comparable to the baseline.
    """
    tc = time_context or {}
    if weather is None:
        weather = tc.get("weather", "clear")

    G = graph.copy() if copy_graph else graph

    od_used = od_matrix
    scale = 1.0
    if auto_calibrate:
        od_used, scale = _calibrate_trips(G, od_matrix, k_paths, weather, target_pressure)

    # Start from free-flow times.
    reset_loads(G)

    frames = []
    for step in range(iterations):
        assign_demand_to_paths(G, od_used, k=k_paths, reset=True)
        update_edge_congestion(G, weather=weather)
        if capture_frames:
            frames.append(_frame(G, step, _label_for(step, iterations)))

    summary = summarize(G, od_used)
    return {
        "time_context": tc,
        "weather": weather,
        "iterations_run": iterations,
        "k_paths": k_paths,
        "calibration_scale": scale,
        "summary": summary,
        "od_matrix": od_used,
        "node_demands": node_demands,
        "frames": frames,
        "graph": G,
    }


def summarize(graph, od_matrix) -> dict:
    """Compute the headline numbers over the final graph state."""
    total_trips = sum(od["trips"] for od in od_matrix)
    pressures = []
    high = severe = closed = 0
    for _, _, d in graph.edges(data=True):
        if d.get("status") == "closed":
            closed += 1
            severe += 1
            continue
        risk = d.get("risk", "low")
        if risk == "high":
            high += 1
        elif risk == "severe":
            severe += 1
        load = d.get("load", 0.0) or 0.0
        cap = d.get("capacity", 0.0) or 0.0
        if load > 0 and cap > 0:
            p = d.get("pressure")
            if p is not None and math.isfinite(p):
                pressures.append(p)
    avg_p = (sum(pressures) / len(pressures)) if pressures else 0.0
    return {
        "total_assigned_trips": round(total_trips, 1),
        "active_edges": len(pressures),
        "average_pressure": round(avg_p, 4),
        "high_risk_edges": high,
        "severe_edges": severe,
        "closed_edges": closed,
    }


# ---------------------------------------------------------------------------
# Scenario simulation + comparison
# ---------------------------------------------------------------------------

def apply_scenario(graph, scenario: List[dict]):
    """Apply a list of mutation ops to `graph` in place. Returns the graph.

    Each op is a dict with an "op" key:
      {"op": "close_edge", "edge_id": ...}
      {"op": "reopen_edge", "edge_id": ...}
      {"op": "remove_edge", "edge_id": ...}
      {"op": "change_capacity", "edge_id": ..., "multiplier": 0.5}
      {"op": "close_node", "node_id": ...}
      {"op": "add_edge", "from_node": .., "to_node": .., "road_name": ..,
                          "speed_kmh": .., "lanes": .., "capacity": ..}
    """
    from ..graph.mutations import (
        add_edge, change_capacity, close_edge, close_node, remove_edge,
        reopen_edge,
    )

    for op in scenario or []:
        kind = op.get("op")
        if kind == "close_edge":
            close_edge(graph, op["edge_id"])
        elif kind == "reopen_edge":
            reopen_edge(graph, op["edge_id"])
        elif kind == "remove_edge":
            remove_edge(graph, op["edge_id"])
        elif kind == "change_capacity":
            change_capacity(graph, op["edge_id"], op["multiplier"])
        elif kind == "close_node":
            close_node(graph, op["node_id"])
        elif kind == "add_edge":
            add_edge(graph, op["from_node"], op["to_node"], op["road_name"],
                     op["speed_kmh"], op["lanes"], op["capacity"])
        else:
            raise ValueError(f"unknown scenario op: {kind!r}")
    return graph


def simulate_scenario(
    graph,
    od_matrix: List[dict],
    scenario: List[dict],
    iterations: int = 4,
    k_paths: int = 3,
    weather: Optional[str] = None,
    time_context: Optional[dict] = None,
    capture_frames: bool = True,
) -> dict:
    """Apply `scenario` to a copy of `graph`, then simulate on the SAME trips.

    Calibration is OFF so the scenario uses identical demand to the baseline,
    making `compare_simulations` an apples-to-apples diff.
    """
    G = graph.copy()
    from ..graph.routing import build_edge_index
    build_edge_index(G)
    apply_scenario(G, scenario)
    result = simulate_traffic(
        G, od_matrix, iterations=iterations, k_paths=k_paths, weather=weather,
        time_context=time_context, auto_calibrate=False,
        capture_frames=capture_frames, copy_graph=False,
    )
    result["scenario"] = scenario
    return result


def compare_simulations(baseline_result: dict, scenario_result: dict) -> dict:
    """Diff two simulation results: summary deltas + most-changed edges."""
    bg, sg = baseline_result["graph"], scenario_result["graph"]

    def edge_map(g):
        m = {}
        for _, _, d in g.edges(data=True):
            m[d.get("edge_id")] = d
        return m

    bmap, smap = edge_map(bg), edge_map(sg)
    changes = []
    for eid, sd in smap.items():
        bd = bmap.get(eid)
        b_time = _finite(bd.get("current_time_min")) if bd else None
        s_time = _finite(sd.get("current_time_min"))
        b_load = (bd.get("load", 0.0) or 0.0) if bd else 0.0
        s_load = sd.get("load", 0.0) or 0.0
        b_press = _finite(bd.get("pressure")) if bd else None
        s_press = _finite(sd.get("pressure"))
        dload = s_load - b_load
        dpress = (s_press - b_press) if (b_press is not None and s_press is not None) else None
        changes.append({
            "edge_id": eid,
            "road_name": sd.get("road_name"),
            "load_before": round(b_load, 1),
            "load_after": round(s_load, 1),
            "load_delta": round(dload, 1),
            "pressure_before": _r(b_press),
            "pressure_after": _r(s_press),
            "pressure_delta": _r(dpress),
            "time_before": _r(b_time),
            "time_after": _r(s_time),
            "status_after": sd.get("status"),
        })

    # Most-impacted edges by absolute load change.
    changes.sort(key=lambda c: -abs(c["load_delta"]))
    bs, ss = baseline_result["summary"], scenario_result["summary"]
    return {
        "summary_delta": {
            "average_pressure": _r(ss["average_pressure"] - bs["average_pressure"]),
            "high_risk_edges": ss["high_risk_edges"] - bs["high_risk_edges"],
            "severe_edges": ss["severe_edges"] - bs["severe_edges"],
            "active_edges": ss["active_edges"] - bs["active_edges"],
        },
        "baseline_summary": bs,
        "scenario_summary": ss,
        "most_impacted_edges": changes[:50],
    }


def _finite(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _r(v):
    return None if v is None else round(v, 4)
