"""Auto-optimizer (P10): constrained intervention proposals, sim-verified.

Generates candidate intervention plans over a constrained action space, **scores
each by actually running the simulation** (the sim is the verifier — the Prime
Intellect / Verifiers story), masks illegal/unsafe actions, and returns ranked
improving plans the planner can one-click apply. A reliable heuristic baseline
always returns something better-or-neutral; cuOpt is a Spark-gated add-on for
constrained sub-problems (never on the critical path).
"""

from __future__ import annotations

from .heuristic import propose

__all__ = ["propose"]
