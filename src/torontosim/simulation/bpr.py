"""BPR volume-delay function (P04).

    t = t0 * (1 + alpha * (v / c) ** beta)

Standard US BPR parameters are alpha=0.15, beta=4 (BPR 1964). Per-road-class
overrides live in ``graph.config.BPR_PARAMS``. A closed / zero-capacity edge
returns ``inf`` so it carries no equilibrium flow.
"""

from __future__ import annotations

from functools import lru_cache

ALPHA = 0.15
BETA = 4.0


def bpr_time(t0: float, v: float, c: float, *, alpha: float = ALPHA, beta: float = BETA) -> float:
    """Congested travel time for a link at volume ``v``, capacity ``c``.

    ``v=0`` -> ``t0``; ``v=c`` -> ``t0*(1+alpha)``; ``c<=0`` -> ``inf``.
    """
    if c <= 0:
        return float("inf")
    return t0 * (1.0 + alpha * (v / c) ** beta)


@lru_cache(maxsize=None)
def bpr_params_for(road_class: str) -> tuple[float, float]:
    """Look up (alpha, beta) for a road class (falls back to the global BPR).

    Memoized: called once per edge per congestion pass (~326k/sim) but over a
    tiny finite set of road classes, so the lookup + module import runs once
    per class, not once per call.
    """
    from ..graph.config import BPR_PARAMS

    return BPR_PARAMS.get(road_class, BPR_PARAMS["default"])
