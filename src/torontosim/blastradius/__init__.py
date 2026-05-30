"""Blast-radius adaptive subgraph recompute (P05).

When a planner makes a local intervention, recompute only the affected subgraph
instead of re-solving all of Toronto. Affected-path detection is O(1) via a
reverse index (``pathcache``); the affected region is grown with bounded
upstream/downstream cones (``cones``); ``recompute`` re-routes only the affected
OD bundles and adaptively widens if boundary pressures shift.

``recompute=full`` (Liron's path) is always the correctness fallback; blast is a
performance upgrade.
"""

from __future__ import annotations

__all__ = ["pathcache", "cones", "recompute"]
