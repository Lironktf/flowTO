"""Heuristic optimizer entry (P10): ``propose(state, payload)``.

Always returns an improving-or-neutral, budget- and bylaw-valid plan, each
candidate **scored by running the sim**. cuOpt (Spark) can refine constrained
sub-problems but is never required here.
"""

from __future__ import annotations

from .problem import problem_from_payload
from .search import greedy_search


def propose(state, payload: dict | None = None) -> dict:
    """Return a ranked, sim-verified intervention plan for the problem.

    ``payload`` may set ``objective`` / ``budget`` / ``max_actions`` /
    ``candidate_k`` / ``capacity_multiplier`` / ``action_space``.
    """
    problem = problem_from_payload(payload or {})
    result = greedy_search(state, problem)
    result["solver"] = "heuristic"
    result["note"] = (
        "Each candidate scored by simulating it (the sim is the verifier). "
        "Plan is bylaw- and budget-valid; never worse than do-nothing."
    )
    return result
