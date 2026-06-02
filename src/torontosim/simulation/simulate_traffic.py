"""
The propagation loop — the heart of the simulation.

    simulate_traffic(graph, od_matrix, iterations=4, k_paths=3) -> result

Each iteration:
  1. zero edge loads
  2. assign OD trips to the top-k paths using *current* (congested) edge times
  3. recompute pressure / travel time / risk for every edge
  4. snapshot the edge states (a "frame" for animation)

Because step 2 routes on the times produced by step 3 of the previous
iteration, congestion propagates: a road that overloaded last round is slower
this round, so some drivers shift to alternates — which may then congest too.
The final iteration is the stabilised baseline.

Scenario simulation reuses the exact same machinery: mutate the graph (close /
add / remove / re-capacity an edge), then run `simulate_traffic` again on the
*same* OD matrix and `compare_simulations` the two results.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional

from .assign_paths import assign_demand_to_paths
from .congestion import reset_loads, update_edge_congestion

INF = float("inf")


def resolve_blast_backend() -> str:
    """Backend for blast-path sims (path cache + blast reroute), used by the
    copilot scenario loop and the ``blast_baseline`` compare reference.

    GPU when ``TS_BACKEND=gpu`` (cuGraph, Spark only); otherwise **scipy** — the
    vectorized ``csgraph.dijkstra`` over all origins, which needs no special
    hardware and is strictly faster than the plain-CPU NetworkX heap. Plain
    ``cpu`` is never chosen here on purpose: there's no host where it beats scipy
    for this path. Both fall back to CPU internally if their dep is missing.
    """
    return "gpu" if os.environ.get("TS_BACKEND") == "gpu" else "scipy"

# Auto-calibration target: scale total trips so the median loaded edge sits near
# this pressure. Keeps output plausible regardless of raw demand magnitudes.
DEFAULT_TARGET_PRESSURE = 0.55


def _loaded_pressures(graph):
    out = []
    for _, _, d in graph.edges(data=True):
        if d.get("status") == "closed":
            continue
        load = d.get("load", 0.0) or 0.0
        cap = d.get("capacity", 0.0) or 0.0
        if load > 0 and cap > 0:
            p = d.get("pressure")
            if p is not None and math.isfinite(p):
                out.append(p)
    return out


def _calibrate_trips(graph, od_matrix, k_paths, weather, target_pressure):
    """Return an OD list scaled so the mean loaded-edge pressure ≈ target.

    Pressure is linear in trips for a fixed routing pattern, so one assignment
    pass tells us the scale factor. Uses a single vectorized scipy all-or-nothing
    pass (fast — ~0.5s vs ~45s for the NetworkX k-path pass); falls back to the
    k-path pass if the scipy path is unavailable. Non-destructive.
    """
    scale = _estimate_scale_scipy(graph, od_matrix, weather, target_pressure)
    if scale is None:
        # Fallback: original NetworkX k-path calibration.
        reset_loads(graph)
        assign_demand_to_paths(graph, od_matrix, k=k_paths, reset=True)
        update_edge_congestion(graph, weather=weather)
        pressures = _loaded_pressures(graph)
        reset_loads(graph)
        if not pressures:
            return [dict(od) for od in od_matrix], 1.0
        mean_p = sum(pressures) / len(pressures)
        scale = (target_pressure / mean_p) if mean_p > 0 else 1.0
        scale = max(0.01, min(100.0, scale))
    scaled = [{**od, "trips": od["trips"] * scale} for od in od_matrix]
    return scaled, scale


def _estimate_scale_scipy(graph, od_matrix, weather, target_pressure):
    """Mean loaded-edge v/c from a single scipy AON -> trip scale factor.

    Returns ``None`` if scipy/Network construction is unavailable so the caller
    can fall back to the NetworkX path.
    """
    try:
        import numpy as np

        from ..model.features import weather_speed_factor
        from .backends import scipy_backend
        from .equilibrium import network_from_graph

        wfac = weather_speed_factor(weather) or 1.0
        net, node_index, _edge_keys = network_from_graph(graph, weather_factor=wfac)
        costs = np.where(net.cap > 0, net.t0, np.inf).astype(np.float64)

        od_by_origin: dict = {}
        for od in od_matrix:
            o = node_index.get(od["origin"])
            d = node_index.get(od["destination"])
            trips = float(od.get("trips", 0.0))
            if o is not None and d is not None and trips > 0:
                od_by_origin.setdefault(o, []).append((d, trips))
        if not od_by_origin:
            return None

        flow = scipy_backend.all_or_nothing(net, costs, od_by_origin)
        mask = (net.cap > 0) & (flow > 0)
        if not mask.any():
            return None
        mean_p = float(np.mean(flow[mask] / net.cap[mask]))
        if mean_p <= 0:
            return None
        return max(0.01, min(100.0, target_pressure / mean_p))
    except Exception:  # noqa: BLE001 — fall back to the NetworkX path
        return None


def _frame(graph, step, label, only_active=True):
    """Compact per-iteration snapshot of edge states for animation."""
    states = []
    for u, v, d in graph.edges(data=True):
        load = d.get("load", 0.0) or 0.0
        if only_active and load <= 0 and d.get("status") != "closed":
            continue
        states.append(
            {
                "edge_id": d.get("edge_id"),
                "load": round(load, 1),
                "pressure": _num(d.get("pressure")),
                "current_time_min": _num(d.get("current_time_min")),
                "risk": d.get("risk", "low"),
            }
        )
    return {"step": step, "label": label, "edge_states": states}


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return "Infinity" if math.isinf(f) else round(f, 4)


_LABELS = [
    "initial assignment",
    "first congestion update",
    "secondary rerouting",
    "stabilized baseline",
]


def _label_for(step, iterations):
    if step == iterations - 1:
        return "stabilized baseline"
    if step < len(_LABELS):
        return _LABELS[step]
    return f"rerouting pass {step}"


def simulate_traffic(
    graph,
    od_matrix: List[dict],
    iterations: int = 4,
    k_paths: int = 3,
    weather: Optional[str] = None,
    time_context: Optional[dict] = None,
    node_demands: Optional[Dict[object, float]] = None,
    auto_calibrate: bool = True,
    target_pressure: float = DEFAULT_TARGET_PRESSURE,
    capture_frames: bool = True,
    copy_graph: bool = True,
    engine: str = "kpath",
    congestion_model: str = "legacy",
    backend: str = "cpu",
    rgap_target: float = 1e-4,
    max_equilibrium_iter: int = 100,
) -> dict:
    """Run the assignment + propagation loop and return a simulation result dict.

    Flags (P04 — all default to the demo-safe baseline per GOAL):
      * ``engine``: ``kpath`` (Liron's all-or-nothing top-k loop, default/fast)
        | ``equilibrium`` (BPR + Frank-Wolfe user equilibrium).
      * ``congestion_model``: ``legacy`` (lookup table) | ``bpr``.
      * ``backend``: ``cpu`` (NetworkX/Dijkstra) | ``gpu`` (cuGraph, Spark only).

    The input graph is copied by default so the caller's graph is untouched
    (set copy_graph=False to mutate in place). The returned `od_matrix` is the
    (possibly calibrated) one actually used — pass it to `simulate_scenario` so
    the scenario is comparable to the baseline.
    """
    tc = time_context or {}
    if weather is None:
        weather = tc.get("weather", "clear")

    G = graph.copy() if copy_graph else graph

    od_used = od_matrix
    scale = 1.0
    if auto_calibrate:
        od_used, scale = _calibrate_trips(G, od_matrix, k_paths, weather, target_pressure)

    # Start from free-flow times.
    reset_loads(G)

    from ..perf.timing import timer

    if engine == "equilibrium":
        with timer(f"assign_{engine}_{backend}"):
            frames, eq = _run_equilibrium(
                G,
                od_used,
                iterations=iterations,
                weather=weather,
                congestion_model=congestion_model,
                backend=backend,
                rgap_target=rgap_target,
                max_iter=max_equilibrium_iter,
                capture_frames=capture_frames,
            )
    else:
        eq = None
        frames = []
        with timer(f"assign_{engine}"):
            _kpath_loop(
                G,
                od_used,
                k_paths,
                iterations,
                weather,
                congestion_model,
                capture_frames,
                frames,
                backend,
            )
    summary = summarize(G, od_used)
    result = {
        "time_context": tc,
        "weather": weather,
        "engine": engine,
        "congestion_model": congestion_model,
        "backend": backend,
        "iterations_run": iterations,
        "k_paths": k_paths,
        "calibration_scale": scale,
        "summary": summary,
        "od_matrix": od_used,
        "node_demands": node_demands,
        "frames": frames,
        "graph": G,
    }
    if eq is not None:
        result["rgap"] = eq.rgap
        result["equilibrium_iterations"] = eq.iterations
        result["converged"] = eq.converged
    return result


def _kpath_loop(
    G,
    od_used,
    k_paths,
    iterations,
    weather,
    congestion_model,
    capture_frames,
    frames,
    backend="cpu",
):
    """Liron's all-or-nothing top-k propagation loop (the baseline engine)."""
    for step in range(iterations):
        assign_demand_to_paths(G, od_used, k=k_paths, reset=True, backend=backend)
        update_edge_congestion(G, weather=weather, congestion_model=congestion_model)
        if capture_frames:
            frames.append(_frame(G, step, _label_for(step, iterations)))


def _run_equilibrium(
    G,
    od_used,
    *,
    iterations,
    weather,
    congestion_model,
    backend,
    rgap_target,
    max_iter,
    capture_frames,
):
    """Solve UE then build `iterations` display frames as a deterministic ramp.

    Frank-Wolfe yields one converged flow; for the scrub animation we replay it
    as a load ramp (step (s+1)/iterations of the equilibrium flow) so the demo
    shows congestion building to the true equilibrium on the final frame.
    """
    from ..model.features import weather_speed_factor
    from .equilibrium import assign_equilibrium

    wfac = weather_speed_factor(weather) or 1.0
    eq = assign_equilibrium(
        G,
        od_used,
        weather_factor=wfac,
        max_iter=max_iter,
        rgap_target=rgap_target,
        backend=backend,
    )
    # Equilibrium load now lives on each edge; capture the ramp frames.
    eq_load = {(u, v, k): d.get("load", 0.0) for u, v, k, d in G.edges(keys=True, data=True)}
    frames = []
    steps = max(iterations, 1)
    for step in range(steps):
        frac = (step + 1) / steps
        for u, v, k, d in G.edges(keys=True, data=True):
            d["load"] = eq_load[(u, v, k)] * frac
        update_edge_congestion(G, weather=weather, congestion_model=congestion_model)
        if capture_frames:
            frames.append(_frame(G, step, _label_for(step, iterations)))
    return frames, eq


def summarize(graph, od_matrix) -> dict:
    """Compute the headline numbers over the final graph state."""
    total_trips = sum(od["trips"] for od in od_matrix)
    pressures = []
    high = severe = closed = 0
    for _, _, d in graph.edges(data=True):
        if d.get("status") == "closed":
            closed += 1
            severe += 1
            continue
        risk = d.get("risk", "low")
        if risk == "high":
            high += 1
        elif risk == "severe":
            severe += 1
        load = d.get("load", 0.0) or 0.0
        cap = d.get("capacity", 0.0) or 0.0
        if load > 0 and cap > 0:
            p = d.get("pressure")
            if p is not None and math.isfinite(p):
                pressures.append(p)
    avg_p = (sum(pressures) / len(pressures)) if pressures else 0.0
    stranded = _count_stranded_trips(graph, od_matrix)
    return {
        "total_assigned_trips": round(total_trips, 1),
        "active_edges": len(pressures),
        "average_pressure": round(avg_p, 4),
        "high_risk_edges": high,
        "severe_edges": severe,
        "closed_edges": closed,
        "stranded_trips": round(stranded, 1),
    }


def _count_stranded_trips(graph, od_matrix) -> float:
    """Total OD demand with NO route under the current graph (free-flow costs).

    Surfaces trips a closure leaves un-routable instead of silently dropping
    them — so a road closure that disconnects destinations shows up as a cost,
    not a phantom improvement. Best-effort: returns 0.0 if the routing check
    can't run (e.g. scipy unavailable).
    """
    try:
        import numpy as np
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import dijkstra

        from .backends.scipy_backend import _eff_costs, _structure
        from .equilibrium import network_from_graph

        net, node_index, _edge_keys = network_from_graph(graph)
        costs = np.where(net.cap > 0, net.t0, np.inf).astype(np.float64)
        od = [
            (node_index[e["origin"]], node_index[e["destination"]], float(e.get("trips", 0.0)))
            for e in od_matrix
            if e["origin"] in node_index
            and e["destination"] in node_index
            and e.get("trips", 0) > 0
        ]
        if not od:
            return 0.0

        # Stranded counting needs only *reachability*, not traced paths, so one
        # vectorized scipy dijkstra over the unique origins answers it directly:
        # a trip is stranded iff its destination sits at infinite cost from its
        # origin under free-flow costs. We reuse the exact CSR the scipy AON
        # backend builds (parallel edges collapsed to min cost per (tail, head))
        # so reachability matches how flow is actually routed. The old path lay
        # through build_path_cache(backend="scipy"), which has no scipy branch
        # and silently fell back to a per-origin heap Dijkstra (~25s vs <1s).
        eff = _eff_costs(net, costs)
        pair_rows, pair_cols, pair_index, fin_idx, _lut = _structure(net, eff)
        pair_min = np.full(pair_rows.shape[0], np.inf, dtype=np.float64)
        np.minimum.at(pair_min, pair_index, eff[fin_idx])
        csr = csr_matrix((pair_min, (pair_rows, pair_cols)), shape=(net.n_nodes, net.n_nodes))

        origins = sorted({o for o, _d, _t in od})
        row_of = {o: i for i, o in enumerate(origins)}
        dist = dijkstra(csr, directed=True, indices=origins, return_predecessors=False)

        return float(sum(t for o, d, t in od if not np.isfinite(dist[row_of[o], d])))
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------
# Scenario simulation + comparison
# ---------------------------------------------------------------------------


def apply_scenario(graph, scenario: List[dict]):
    """Apply a list of mutation ops to `graph` in place. Returns the graph.

    Each op is a dict with an "op" key:
      {"op": "close_edge", "edge_id": ...}
      {"op": "reopen_edge", "edge_id": ...}
      {"op": "remove_edge", "edge_id": ...}
      {"op": "change_capacity", "edge_id": ..., "multiplier": 0.5}
      {"op": "close_node", "node_id": ...}
      {"op": "add_edge", "from_node": .., "to_node": .., "road_name": ..,
                          "speed_kmh": .., "lanes": .., "capacity": ..}
    """
    from ..graph.mutations import (
        add_edge,
        change_capacity,
        close_edge,
        close_node,
        remove_edge,
        reopen_edge,
    )

    for op in scenario or []:
        kind = op.get("op")
        if kind == "close_edge":
            close_edge(graph, op["edge_id"])
        elif kind == "reopen_edge":
            reopen_edge(graph, op["edge_id"])
        elif kind == "remove_edge":
            remove_edge(graph, op["edge_id"])
        elif kind == "change_capacity":
            change_capacity(graph, op["edge_id"], op["multiplier"])
        elif kind == "close_node":
            close_node(graph, op["node_id"])
        elif kind == "add_edge":
            add_edge(
                graph,
                op["from_node"],
                op["to_node"],
                op["road_name"],
                op["speed_kmh"],
                op["lanes"],
                op["capacity"],
            )
        else:
            raise ValueError(f"unknown scenario op: {kind!r}")
    return graph


def simulate_scenario(
    graph,
    od_matrix: List[dict],
    scenario: List[dict],
    iterations: int = 4,
    k_paths: int = 3,
    weather: Optional[str] = None,
    time_context: Optional[dict] = None,
    capture_frames: bool = True,
    engine: str = "kpath",
    congestion_model: str = "legacy",
    backend: str = "cpu",
    recompute: str = "full",
    rgap_target: float = 1e-4,
    max_equilibrium_iter: int = 100,
) -> dict:
    """Apply `scenario` to a copy of `graph`, then simulate on the SAME trips.

    Calibration is OFF so the scenario uses identical demand to the baseline,
    making `compare_simulations` an apples-to-apples diff.

    ``recompute`` (P05): ``full`` re-solves the whole network (default, always
    correct); ``blast`` re-routes only the OD bundles affected by the change
    over an adaptive subgraph (the headline performance feature).

    ``rgap_target`` / ``max_equilibrium_iter`` control the Frank-Wolfe stopping
    rule when ``engine="equilibrium"`` (looser/fewer = faster, demo-grade).
    """
    G = graph.copy()
    from ..graph.routing import build_edge_index

    build_edge_index(G)

    # Demand-surge ops change the OD, not the graph — split them out so
    # apply_scenario (graph-only) never sees them, then transform the demand.
    graph_ops = [op for op in (scenario or []) if op.get("op") != "demand_surge"]
    surge_ops = [op for op in (scenario or []) if op.get("op") == "demand_surge"]
    apply_scenario(G, graph_ops)

    od_used = od_matrix
    if surge_ops:
        from .demand import apply_demand_surge

        for op in surge_ops:
            od_used = apply_demand_surge(
                od_used,
                G,
                node_id=op.get("node_id"),
                lng=op.get("lng"),
                lat=op.get("lat"),
                amount=op.get("amount", 5000.0),
                mode=op.get("mode", "absolute"),
                directions=op.get("directions"),
            )
        # Demand changes the whole assignment — blast (graph-edge-keyed) can't see
        # the new OD bundles, so a surge forces a correct full re-solve.
        recompute = "full"

    if recompute == "blast":
        result = _run_blast_scenario(
            G,
            od_used,
            weather,
            time_context,
            congestion_model,
            iterations,
            capture_frames,
            backend,
        )
    else:
        result = simulate_traffic(
            G,
            od_used,
            iterations=iterations,
            k_paths=k_paths,
            weather=weather,
            time_context=time_context,
            auto_calibrate=False,
            capture_frames=capture_frames,
            copy_graph=False,
            engine=engine,
            congestion_model=congestion_model,
            backend=backend,
            rgap_target=rgap_target,
            max_equilibrium_iter=max_equilibrium_iter,
        )
    result["scenario"] = scenario
    result["recompute"] = recompute
    return result


def _run_blast_scenario(
    G, od_matrix, weather, time_context, congestion_model, iterations, capture_frames, backend="cpu"
):
    """Blast-radius scenario: re-route only affected ODs over an adaptive subgraph.

    Builds the link network from the (already-mutated) graph, detects which links
    became closed, re-routes only the OD bundles that used them, and loads the
    result back — recomputing congestion + the display frames. Reports the
    affected-subgraph fraction as the performance evidence.
    """
    import numpy as np

    from ..blastradius.pathcache import build_path_cache
    from ..blastradius.recompute import blast_assign
    from ..model.features import weather_speed_factor
    from .equilibrium import network_from_graph

    tc = time_context or {}
    if weather is None:
        weather = tc.get("weather", "clear")
    wfac = weather_speed_factor(weather) or 1.0

    net, node_index, edge_keys = network_from_graph(G, weather_factor=wfac)
    od = [
        (node_index[e["origin"]], node_index[e["destination"]], float(e.get("trips", 0.0)))
        for e in od_matrix
        if e["origin"] in node_index and e["destination"] in node_index and e.get("trips", 0) > 0
    ]
    # Free-flow baseline cache (before the closures take cost effect).
    base_costs = net.t0.copy()
    cache = build_path_cache(net, od, base_costs, backend=backend)

    # Changed links = those now closed/zero-capacity in the mutated graph.
    new_costs = base_costs.copy()
    changed = []
    for i, (u, v, k) in enumerate(edge_keys):
        if net.cap[i] <= 0:  # closed/removed by the scenario op
            new_costs[i] = np.inf
            changed.append(i)

    res = blast_assign(net, od, cache, changed, new_costs, backend=backend)
    for i, (u, v, k) in enumerate(edge_keys):
        if G.has_edge(u, v, k):
            G[u][v][k]["load"] = float(res.flow[i])

    eq_load = {(u, v, k): G[u][v][k]["load"] for (u, v, k) in edge_keys if G.has_edge(u, v, k)}
    frames = []
    steps = max(iterations, 1)
    for step in range(steps):
        frac = (step + 1) / steps
        for key, load in eq_load.items():
            u, v, k = key
            G[u][v][k]["load"] = load * frac
        update_edge_congestion(G, weather=weather, congestion_model=congestion_model)
        if capture_frames:
            frames.append(_frame(G, step, _label_for(step, iterations)))

    return {
        "time_context": tc,
        "weather": weather,
        "engine": "blast",
        "congestion_model": congestion_model,
        "backend": backend,
        "iterations_run": iterations,
        "summary": summarize(G, od_matrix),
        "od_matrix": od_matrix,
        "frames": frames,
        "graph": G,
        "blast_stats": res.stats,
    }


def compare_simulations(baseline_result: dict, scenario_result: dict) -> dict:
    """Diff two simulation results: summary deltas + most-changed edges."""
    bg, sg = baseline_result["graph"], scenario_result["graph"]

    def edge_map(g):
        m = {}
        for _, _, d in g.edges(data=True):
            m[d.get("edge_id")] = d
        return m

    bmap, smap = edge_map(bg), edge_map(sg)
    changes = []
    for eid, sd in smap.items():
        bd = bmap.get(eid)
        b_time = _finite(bd.get("current_time_min")) if bd else None
        s_time = _finite(sd.get("current_time_min"))
        b_load = (bd.get("load", 0.0) or 0.0) if bd else 0.0
        s_load = sd.get("load", 0.0) or 0.0
        b_press = _finite(bd.get("pressure")) if bd else None
        s_press = _finite(sd.get("pressure"))
        dload = s_load - b_load
        dpress = (s_press - b_press) if (b_press is not None and s_press is not None) else None
        changes.append(
            {
                "edge_id": eid,
                "road_name": sd.get("road_name"),
                "load_before": round(b_load, 1),
                "load_after": round(s_load, 1),
                "load_delta": round(dload, 1),
                "pressure_before": _r(b_press),
                "pressure_after": _r(s_press),
                "pressure_delta": _r(dpress),
                "time_before": _r(b_time),
                "time_after": _r(s_time),
                "status_after": sd.get("status"),
            }
        )

    # Most-impacted edges by absolute load change.
    changes.sort(key=lambda c: -abs(c["load_delta"]))
    bs, ss = baseline_result["summary"], scenario_result["summary"]
    return {
        "summary_delta": {
            "average_pressure": _r(ss["average_pressure"] - bs["average_pressure"]),
            "high_risk_edges": ss["high_risk_edges"] - bs["high_risk_edges"],
            "severe_edges": ss["severe_edges"] - bs["severe_edges"],
            "active_edges": ss["active_edges"] - bs["active_edges"],
            # Trips the scenario leaves un-routable beyond the baseline — a real
            # cost of the change, not a phantom improvement from dropped demand.
            "stranded_trips": _r(ss.get("stranded_trips", 0.0) - bs.get("stranded_trips", 0.0)),
        },
        "baseline_summary": bs,
        "scenario_summary": ss,
        "most_impacted_edges": changes[:50],
    }


def _finite(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _r(v):
    return None if v is None else round(v, 4)
