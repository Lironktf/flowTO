"""cuOpt client for constrained sub-problems (P10, Spark-gated add-on).

City traffic is NOT a pure VRP — cuOpt solves the **constrained
assignment/scheduling sub-problem** (OD-bundle reassignment as VRP+capacity,
work-window scheduling as VRP-TW), and the simulation provides realism. This
client is optional: it raises ``CuOptUnavailable`` when the self-hosted cuOpt
service isn't reachable, and the heuristic baseline carries the demo.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

CUOPT_URL = "http://localhost:5000/cuopt/request"


class CuOptUnavailable(RuntimeError):
    pass


def solve_vrp(
    problem: dict, *, url: str = CUOPT_URL, timeout: int = 60
) -> dict:  # pragma: no cover
    """POST a cuOpt VRP/assignment problem; return the solution.

    Raises ``CuOptUnavailable`` if the service can't be reached so callers can
    fall back to the heuristic.
    """
    req = urllib.request.Request(
        url, data=json.dumps(problem).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError) as exc:
        raise CuOptUnavailable(str(exc)) from exc
