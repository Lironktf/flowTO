"""Static user-equilibrium assignment: Frank-Wolfe / Conjugate-FW (P04).

Solves Beckmann's UE program with BPR volume-delay, an exact 1-D line search,
and a relative-gap stopping rule — all deterministic (fixed iteration caps, no
wall-clock, float64, deterministic AON tie-breaks in the CPU backend).

  ``frank_wolfe(net, od, algorithm="cfw", max_iter=200, rgap_target=1e-5)``
    -> EquilibriumResult(flow, cost, rgap, iterations, converged)

``algorithm``: ``msa`` | ``fw`` | ``cfw`` (conjugate FW — default, ~AequilibraE
``bfw`` quality with fewer iters than plain FW). The conjugate direction uses
the diagonal BPR Hessian.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import backends
from .network import Network, bpr_costs, build_network


@dataclass
class EquilibriumResult:
    flow: np.ndarray
    cost: np.ndarray
    rgap: float
    iterations: int
    converged: bool
    rgap_history: list


def _od_by_origin(od) -> dict:
    by_o: dict = {}
    for o, d, demand in od:
        if demand <= 0:
            continue
        by_o.setdefault(int(o), []).append((int(d), float(demand)))
    return by_o


def _bpr_hessian_diag(net: Network, flow: np.ndarray) -> np.ndarray:
    """t_i'(x_i) = t0 * alpha * beta * x^(beta-1) / cap^beta (0 if cap<=0)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        h = (
            net.t0
            * net.alpha
            * net.beta
            * np.power(np.maximum(flow, 0.0), net.beta - 1.0)
            / np.power(net.cap, net.beta)
        )
    return np.where(net.cap > 0, h, 0.0)


def _line_search(net: Network, x: np.ndarray, d: np.ndarray, *, iters: int = 60) -> float:
    """Exact step minimizing the (convex) Beckmann objective along x+λd, λ∈[0,1].

    Bisection on dZ/dλ = Σ d_i · t_i(x_i + λ d_i), which is nondecreasing in λ.
    """

    def deriv(lam: float) -> float:
        cost = bpr_costs(net, x + lam * d)
        finite = np.isfinite(cost)
        return float(np.sum(d[finite] * cost[finite]))

    lo, hi = 0.0, 1.0
    dlo, dhi = deriv(lo), deriv(hi)
    if dlo >= 0.0:
        return 0.0
    if dhi <= 0.0:
        return 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if deriv(mid) > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def _relative_gap(cost: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    """rgap = (Σ t·x − Σ t·y) / (Σ t·x). 0 at equilibrium."""
    finite = np.isfinite(cost)
    tx = float(np.sum(cost[finite] * x[finite]))
    ty = float(np.sum(cost[finite] * y[finite]))
    if tx <= 0:
        return float("inf")
    return (tx - ty) / tx


def frank_wolfe(
    net: Network,
    od,
    *,
    algorithm: str = "cfw",
    max_iter: int = 200,
    rgap_target: float = 1e-5,
    backend: str = "cpu",
) -> EquilibriumResult:
    """Solve user equilibrium. See module docstring."""
    od_by_origin = _od_by_origin(od)
    # Step 0: a free-flow all-or-nothing loading gives the first *feasible* flow
    # (x=0 is infeasible — it satisfies no demand — so FW must start here).
    cost = bpr_costs(net, np.zeros(net.n_links, dtype=np.float64))
    x = backends.all_or_nothing(net, cost, od_by_origin, backend=backend)
    cost = bpr_costs(net, x)

    prev_dir = None  # previous search direction (for conjugate methods)
    prev_y = None
    rgap = float("inf")
    rgap_history: list = []
    converged = False
    it = 0

    for it in range(1, max_iter + 1):
        y = backends.all_or_nothing(net, cost, od_by_origin, backend=backend)

        rgap = _relative_gap(cost, x, y)
        rgap_history.append(rgap)
        if rgap <= rgap_target:
            converged = True
            break

        fw_dir = y - x
        if algorithm in ("cfw", "bfw") and prev_dir is not None and prev_y is not None:
            direction = _conjugate_direction(net, x, fw_dir, prev_dir)
        else:
            direction = fw_dir

        if algorithm == "msa":
            lam = 1.0 / it
        else:
            lam = _line_search(net, x, direction)

        x = x + lam * direction
        # Guard against tiny negative flows from float error.
        np.maximum(x, 0.0, out=x)
        cost = bpr_costs(net, x)
        prev_dir = direction
        prev_y = y

    return EquilibriumResult(
        flow=x,
        cost=cost,
        rgap=rgap,
        iterations=it,
        converged=converged,
        rgap_history=rgap_history,
    )


def network_from_graph(graph, *, weather_factor: float = 1.0):
    """Build a ``Network`` from Liron's MultiDiGraph (one link per edge).

    Free-flow time is ``base_time_min / weather_factor`` (weather slows links);
    closed / zero-capacity edges get capacity 0 -> infinite BPR cost (never
    chosen). Returns ``(net, node_index, edge_keys)`` where ``edge_keys[i]`` is
    the ``(u, v, k)`` of link ``i``.
    """
    from ..graph.config import BPR_PARAMS

    nodes = sorted(graph.nodes(), key=str)
    node_index = {n: i for i, n in enumerate(nodes)}
    tail, head, t0, cap, alpha, beta, edge_ids, edge_keys = [], [], [], [], [], [], [], []
    for u, v, k, d in graph.edges(keys=True, data=True):
        base = d.get("base_time_min", 0.0) or 0.0
        free = base / weather_factor if weather_factor > 0 else float("inf")
        capacity = 0.0 if d.get("status") == "closed" else float(d.get("capacity", 0.0) or 0.0)
        a, b = BPR_PARAMS.get(d.get("road_class", "default"), BPR_PARAMS["default"])
        tail.append(node_index[u])
        head.append(node_index[v])
        t0.append(max(free, 1e-9))
        cap.append(capacity)
        alpha.append(a)
        beta.append(b)
        edge_ids.append(d.get("edge_id"))
        edge_keys.append((u, v, k))
    net = build_network(len(nodes), tail, head, t0, cap, alpha, beta, edge_ids=edge_ids)
    return net, node_index, edge_keys


def assign_equilibrium(
    graph,
    od_matrix,
    *,
    weather_factor: float = 1.0,
    algorithm: str = "cfw",
    max_iter: int = 100,
    rgap_target: float = 1e-4,
    backend: str = "cpu",
) -> EquilibriumResult:
    """Solve UE on ``graph`` and write equilibrium flows onto edge ``load`` (in place).

    OD entries are ``{"origin", "destination", "trips"}`` with graph node ids.
    Nodes absent from the graph are skipped. Returns the ``EquilibriumResult``.
    """
    net, node_index, edge_keys = network_from_graph(graph, weather_factor=weather_factor)
    od = []
    for entry in od_matrix:
        o = node_index.get(entry["origin"])
        d = node_index.get(entry["destination"])
        trips = float(entry.get("trips", 0.0))
        if o is not None and d is not None and trips > 0:
            od.append((o, d, trips))

    res = frank_wolfe(
        net,
        od,
        algorithm=algorithm,
        max_iter=max_iter,
        rgap_target=rgap_target,
        backend=backend,
    )
    for i, (u, v, k) in enumerate(edge_keys):
        graph[u][v][k]["load"] = float(res.flow[i])
    return res


def _conjugate_direction(net, x, fw_dir, prev_dir):
    """Conjugate-FW direction: blend the FW direction with the previous one.

    a = (prev_dir^T H fw_dir) / (prev_dir^T H (fw_dir − prev_dir)), clamped to
    [0, 1−ε]; d = (1−a)·fw_dir + a·prev_dir. H = diagonal BPR Hessian at x.
    Falls back to the plain FW direction when the denominator is degenerate.
    """
    h = _bpr_hessian_diag(net, x)
    num = float(np.sum(prev_dir * h * fw_dir))
    den = float(np.sum(prev_dir * h * (fw_dir - prev_dir)))
    if den == 0.0 or not np.isfinite(den):
        return fw_dir
    a = num / den
    if not np.isfinite(a):
        return fw_dir
    a = min(max(a, 0.0), 1.0 - 1e-4)
    return (1.0 - a) * fw_dir + a * prev_dir
