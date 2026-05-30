"""
Edge congestion: pressure, risk, and the load -> travel-time feedback.

    pressure = load / capacity
    current_time_min = base_time_min * congestion_multiplier(pressure)

This feedback is what makes propagation work: more load -> higher pressure ->
slower edge -> drivers reroute on the next assignment pass.
"""

from __future__ import annotations

import math

from ..model.features import weather_speed_factor

INF = float("inf")


def risk_for_pressure(pressure: float) -> str:
    """Risk band for a pressure ratio (closed/infinite -> 'severe')."""
    if pressure is None or math.isinf(pressure):
        return "severe"
    if pressure < 0.50:
        return "low"
    if pressure < 0.75:
        return "moderate"
    if pressure < 1.00:
        return "high"
    return "severe"


def congestion_multiplier(pressure: float) -> float:
    """Travel-time multiplier as a function of pressure (the README table)."""
    if math.isinf(pressure):
        return INF
    if pressure < 0.50:
        return 1.0
    if pressure < 0.75:
        return 1.2
    if pressure < 1.00:
        return 1.6
    if pressure < 1.25:
        return 2.2
    return 3.0


def update_edge_congestion(graph, weather: str = "clear", congestion_model: str = "legacy"):
    """Recompute pressure, risk, and current_time_min for every edge in place.

    ``congestion_model``:
      * ``legacy`` — Liron's piecewise lookup multiplier (the baseline).
      * ``bpr``    — BPR ``t = t0·(1 + α·(v/c)^β)`` with per-road-class α/β.

    Closed edges get capacity 0, pressure inf, current_time_min inf, risk
    'severe'. Bad weather lengthens base time a little (lower effective speed).
    """
    wfac = weather_speed_factor(weather)  # <1 in rain/snow
    use_bpr = congestion_model == "bpr"
    if use_bpr:
        from .bpr import bpr_params_for, bpr_time

    for _, _, data in graph.edges(data=True):
        base = data.get("base_time_min", 0.0) or 0.0
        # Weather stretches free-flow time (slower speeds), independent of load.
        weather_base = base / wfac if wfac > 0 else INF

        if data.get("status") == "closed":
            data["capacity"] = 0
            data["pressure"] = INF
            data["current_time_min"] = INF
            data["risk"] = "severe"
            continue

        load = data.get("load", 0.0) or 0.0
        cap = data.get("capacity", 0.0) or 0.0
        pressure = (load / cap) if cap > 0 else INF
        data["pressure"] = pressure
        if use_bpr:
            alpha, beta = bpr_params_for(data.get("road_class", "default"))
            data["current_time_min"] = bpr_time(weather_base, load, cap, alpha=alpha, beta=beta)
        else:
            mult = congestion_multiplier(pressure)
            data["current_time_min"] = INF if math.isinf(mult) else weather_base * mult
        data["risk"] = risk_for_pressure(pressure)
    return graph


def reset_loads(graph):
    """Zero load/pressure and restore current_time_min to (weatherless) base."""
    for _, _, data in graph.edges(data=True):
        data["load"] = 0.0
        if data.get("status") == "closed":
            data["pressure"] = INF
            data["current_time_min"] = INF
            data["risk"] = "severe"
        else:
            data["pressure"] = 0.0
            data["current_time_min"] = data.get("base_time_min", 0.0) or 0.0
            data["risk"] = "low"
    return graph
