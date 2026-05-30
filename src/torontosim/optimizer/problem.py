"""Optimization problem spec (P10).

objective = minimize a network metric (default average pressure / delay proxy)
subject to bylaw + budget + safety constraints over a discrete action space.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OptimizeProblem:
    objective: str = "average_pressure"  # metric to minimize (lower is better)
    budget: float = 100.0  # arbitrary capital units
    max_actions: int = 3  # plan size cap
    candidate_k: int = 8  # how many congested edges to consider
    capacity_multiplier: float = 1.5  # lane-allocation / signal-retiming proxy
    # action types allowed in the search (subset of mutations + capacity changes)
    action_space: list = field(default_factory=lambda: ["change_capacity", "close_edge"])


def problem_from_payload(payload: dict) -> OptimizeProblem:
    p = OptimizeProblem()
    for k in ("objective", "budget", "max_actions", "candidate_k", "capacity_multiplier"):
        if k in payload and payload[k] is not None:
            setattr(p, k, payload[k])
    if payload.get("action_space"):
        p.action_space = list(payload["action_space"])
    return p
