"""Greedy generate → mask → score → keep loop (P10). Deterministic (seeded by id)."""

from __future__ import annotations

from .constraints import mask_action, plan_cost, within_budget
from .problem import OptimizeProblem
from .score import score_plan


def _congested_edges(graph, k: int) -> list[str]:
    """Top-k edge_ids by pressure (open edges), tie-broken by edge_id."""
    rows = []
    for _u, _v, d in graph.edges(data=True):
        if d.get("status") == "closed":
            continue
        p = d.get("pressure")
        if isinstance(p, (int, float)) and p != float("inf"):
            rows.append((d.get("edge_id"), p))
    rows.sort(key=lambda r: (-r[1], str(r[0])))
    return [eid for eid, _ in rows[:k] if eid is not None]


def _candidate_actions(state, problem: OptimizeProblem) -> list[dict]:
    """One capacity-uplift action per congested edge (masked)."""
    baseline = state.baseline(congestion_model="bpr")
    edges = _congested_edges(baseline["graph"], problem.candidate_k)
    actions = []
    for eid in edges:
        iv = {"op": "change_capacity", "edge_id": eid, "multiplier": problem.capacity_multiplier}
        ok, _reason = mask_action(iv, state.graph)
        if ok:
            actions.append(iv)
    return actions


def greedy_search(state, problem: OptimizeProblem) -> dict:
    """Rank single actions by simulated improvement, then greedily combine.

    Returns baseline metric, the ranked single-action candidates, and the best
    (budget-bounded, ≤ max_actions) plan — never worse than do-nothing.
    """
    baseline = state.baseline(congestion_model="bpr")
    objective = problem.objective
    from .score import metric_value

    base_metric = metric_value(baseline["summary"], objective)

    # Score every single action.
    singles = []
    for iv in _candidate_actions(state, problem):
        scored = score_plan(state, [iv], objective=objective)
        singles.append(
            {
                "interventions": [iv],
                "metric": scored["metric"],
                "improvement": round(base_metric - scored["metric"], 6),
                "cost": plan_cost([iv]),
            }
        )
    # Best single first (largest improvement, tie-broken by edge id).
    singles.sort(key=lambda s: (-s["improvement"], str(s["interventions"][0]["edge_id"])))

    # Greedy combine: add improving actions within budget + max_actions.
    plan: list[dict] = []
    cur_metric = base_metric
    for cand in singles:
        if len(plan) >= problem.max_actions:
            break
        trial = plan + cand["interventions"]
        if not within_budget(trial, problem.budget):
            continue
        scored = score_plan(state, trial, objective=objective)
        if scored["metric"] <= cur_metric + 1e-9:  # improving or neutral
            plan = trial
            cur_metric = scored["metric"]

    return {
        "objective": objective,
        "baseline_metric": round(base_metric, 6),
        "best_metric": round(cur_metric, 6),
        "improvement": round(base_metric - cur_metric, 6),
        "plan": plan,
        "plan_cost": plan_cost(plan),
        "candidates": singles[: problem.candidate_k],
    }
