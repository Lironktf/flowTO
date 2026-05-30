"""Action masks + budget for the optimizer (P10), shared with the copilot.

Hard-rejects illegal/unsafe actions before they enter the search or the planner
view: no through-capacity boosts on residential/local streets, no closing a
fire-route corridor, transit-priority corridors protected. Each action carries a
budget cost so plans can be budget-bounded.
"""

from __future__ import annotations

# Capital cost (arbitrary units) per action type — used for budget bounding.
ACTION_COST = {
    "change_capacity": 20.0,  # signal retiming / lane reallocation
    "close_edge": 10.0,
    "reopen_edge": 0.0,
    "one_way": 15.0,
    "signal": 12.0,
}


def mask_action(intervention: dict, graph) -> tuple[bool, str]:
    """Return (allowed, reason). A masked action never enters optimization.

    Rules:
      * Don't add through-capacity on residential/local streets (cut-through harm).
      * Don't close a transit-priority corridor.
    """
    op = intervention.get("op")
    eid = intervention.get("edge_id")
    data = _edge_data(graph, eid) if eid else None

    if op == "change_capacity" and (intervention.get("multiplier") or 1.0) > 1.0:
        if data and data.get("road_class") in ("residential", "living_street", "service"):
            return False, "no through-capacity increase on a residential/local street"
    if op == "close_edge" and data and data.get("road_class") == "motorway":
        return False, "cannot fully close an expressway corridor (emergency access)"
    if data and data.get("road_class") == "transit_priority":
        return False, "transit-priority corridor protected"
    return True, ""


def _edge_data(graph, edge_id):
    for _u, _v, d in graph.edges(data=True):
        if d.get("edge_id") == edge_id:
            return d
    return None


def plan_cost(interventions: list) -> float:
    return sum(ACTION_COST.get(iv.get("op"), 10.0) for iv in interventions)


def within_budget(interventions: list, budget: float) -> bool:
    return plan_cost(interventions) <= budget
