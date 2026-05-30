"""Validation-against-past harness (P03).

Recreate a past scenario, simulate it, and compare predicted vs observed
congestion to produce an accuracy number (the demo's credibility stat). The
comparison core is pure + deterministic; the orchestration wrapper runs a
simulation and feeds its edge metrics in.
"""

from __future__ import annotations

from collections.abc import Mapping


def compare_predicted_observed(predicted: Mapping, observed: Mapping) -> dict:
    """Compare two edge->value maps over their **shared** keys.

    Returns ``{n, mae, rmse, pct_error}``. ``pct_error`` is MAE normalized by
    the mean observed magnitude (a stable, finite percentage). Deterministic.
    """
    keys = sorted(set(predicted) & set(observed), key=str)
    n = len(keys)
    if n == 0:
        return {"n": 0, "mae": 0.0, "rmse": 0.0, "pct_error": 0.0}

    abs_err = 0.0
    sq_err = 0.0
    obs_sum = 0.0
    for k in keys:
        p = float(predicted[k])
        o = float(observed[k])
        diff = p - o
        abs_err += abs(diff)
        sq_err += diff * diff
        obs_sum += abs(o)

    mae = abs_err / n
    rmse = (sq_err / n) ** 0.5
    mean_obs = obs_sum / n
    pct = (mae / mean_obs * 100.0) if mean_obs > 0 else 0.0
    return {"n": n, "mae": mae, "rmse": rmse, "pct_error": pct}


def validate_past(
    graph,
    scenario,
    observed: Mapping,
    *,
    time_context: dict,
    metric: str = "pressure",
    iterations: int = 4,
) -> dict:
    """Simulate ``scenario`` on ``graph`` and compare ``metric`` vs ``observed``.

    ``observed`` maps ``edge_id -> value``. Returns the comparison metrics plus
    the predicted map. Deterministic given a deterministic simulator.
    """
    from ..simulation.simulate_traffic import simulate_scenario

    result = simulate_scenario(
        graph,
        scenario.get("od_matrix", []),
        scenario.get("ops", []),
        iterations=iterations,
        k_paths=3,
    )
    g = result["graph"]
    predicted = {
        d["edge_id"]: d.get(metric, 0.0)
        for _u, _v, d in g.edges(data=True)
        if d.get("edge_id") in observed
    }
    out = compare_predicted_observed(predicted, observed)
    out["predicted"] = predicted
    return out
