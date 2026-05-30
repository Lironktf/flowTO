"""Sim-based scoring — the verifier (P10).

Every candidate plan is scored by actually running the simulation (blast-radius
where it helps) and reading the metric off ``compare_simulations``. Lower is
better for the default objective (average pressure). This is the "Verifiers"
story: a plan is only as good as its simulated outcome.
"""

from __future__ import annotations

from ..simulation.simulate_traffic import simulate_scenario


def metric_value(summary: dict, objective: str) -> float:
    if objective == "average_pressure":
        return float(summary.get("average_pressure", 0.0))
    if objective == "congested":
        return float(summary.get("high_risk_edges", 0) + summary.get("severe_edges", 0))
    return float(summary.get(objective, 0.0))


def score_plan(state, interventions: list, *, objective: str, recompute: str = "full") -> dict:
    """Run a plan and return its simulated metric + summary. Deterministic."""
    result = simulate_scenario(
        state.graph,
        state.od_matrix,
        interventions,
        weather=state.weather,
        time_context=state.time_context,
        congestion_model="bpr",
        recompute=recompute,
    )
    return {
        "metric": metric_value(result["summary"], objective),
        "summary": result["summary"],
    }
