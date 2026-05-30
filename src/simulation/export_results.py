"""
Serialise a simulation result to the baseline JSON format (Part 7).

    export_baseline_result(simulation_result, path)

The full per-iteration edge states can be large, so by default we keep frames
to the *active* edges only (those carrying load, plus closures). Pass
include_frames=False to drop them entirely, or frame_high_pressure_only=True to
keep only congested edges per frame.
"""

from __future__ import annotations

import json
import math
import os
from typing import Optional

INF = float("inf")


def _num(v):
    """JSON-safe number (infinity -> the string 'Infinity')."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return "Infinity" if math.isinf(f) else round(f, 4)


def build_result_json(
    result: dict,
    od_sample: int = 50,
    node_sample: int = 0,
    include_frames: bool = True,
    frame_high_pressure_only: bool = False,
) -> dict:
    """Build the export dict from a simulate_traffic result."""
    graph = result["graph"]
    tc = result.get("time_context", {})

    edges_out = []
    for u, v, d in graph.edges(data=True):
        edges_out.append({
            "edge_id": d.get("edge_id"),
            "from_node": u,
            "to_node": v,
            "road_name": d.get("road_name"),
            "road_class": d.get("road_class"),
            "load": round(d.get("load", 0.0) or 0.0, 1),
            "capacity": d.get("capacity"),
            "pressure": _num(d.get("pressure")),
            "base_time_min": d.get("base_time_min"),
            "current_time_min": _num(d.get("current_time_min")),
            "risk": d.get("risk", "low"),
            "status": d.get("status", "open"),
        })

    nodes_out = []
    demands = result.get("node_demands") or {}
    if demands:
        items = sorted(demands.items(), key=lambda kv: -kv[1])
        if node_sample and node_sample > 0:
            items = items[:node_sample]
        for node, dem in items:
            nodes_out.append({
                "node_id": node,
                "name": graph.nodes[node].get("name") if node in graph else None,
                "predicted_demand": round(float(dem), 1),
            })

    od = result.get("od_matrix", [])
    od_sorted = sorted(od, key=lambda o: -o["trips"])
    od_out = [{"origin": o["origin"], "destination": o["destination"],
               "trips": round(o["trips"], 1)} for o in od_sorted[:od_sample]]

    frames_out = []
    if include_frames:
        for fr in result.get("frames", []):
            states = fr["edge_states"]
            if frame_high_pressure_only:
                states = [s for s in states
                          if s.get("risk") in ("high", "severe")]
            frames_out.append({"step": fr["step"], "label": fr["label"],
                               "edge_states": states})

    return {
        "time_context": tc,
        "weather": result.get("weather"),
        "summary": result.get("summary", {}),
        "calibration_scale": result.get("calibration_scale"),
        "edges": edges_out,
        "nodes": nodes_out,
        "od_matrix_sample": od_out,
        "iterations": frames_out,
    }


def export_baseline_result(result: dict, path: str, **kwargs) -> dict:
    """Write the baseline result JSON to `path` and return the dict."""
    out = build_result_json(result, **kwargs)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    return out
