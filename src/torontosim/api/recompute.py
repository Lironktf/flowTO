"""Stateless, cached, param-driven simulation.

This is the path that makes the front-end's parameters actually move traffic.
Given a demand model, a time context (hour / day_of_week / month / weather), and
the user's modifications (closures + demand surges), it runs the real pipeline
from ``tests/test_simulation.py``:

    predict_node_demand -> apply demand surges -> build_grounded_od
      -> simulate_scenario (equilibrium / scipy / BPR, full recompute)
      -> per-edge Record5

Results are cached on (model, time_context, interventions) so re-requesting an
identical input is instant. Surges change *demand* (applied before OD); closures
change the *graph* (applied inside ``simulate_scenario``). A changed OD makes the
``blast`` recompute invalid, so this always uses ``recompute="full"``.
"""

from __future__ import annotations

import json
import threading
from typing import List, Optional

from ..model.demand_surge import apply_od_changes
from ..model.features import normalize_time_context
from ..model.odme_calibrate import build_grounded_od
from ..model.predict_node_demand import load_demand_model, predict_node_demand
from ..simulation.simulate_traffic import simulate_scenario
from . import residual_edit
from .store import edge_records

# Graph-mutation ops applied to the network (everything else is demand-side).
_GRAPH_OPS = {
    "close_edge",
    "reopen_edge",
    "remove_edge",
    "change_capacity",
    "close_node",
    "add_edge",
}

# Bound the LRU so a long-lived server doesn't grow without limit. Each entry
# holds ~73k Record5 rows + a summary (a few MB), never the heavy result graph.
_CACHE_MAX = 64


def recompute_scenario(
    state,
    *,
    model_kind: str = "xgboost",
    time_context: Optional[dict] = None,
    interventions: Optional[List[dict]] = None,
    iterations: int = 4,
) -> dict:
    """Run (or fetch from cache) a param-driven simulation.

    Returns ``{records, summary, rgap, model_actual, cached}``. ``model_actual``
    is the demand model that actually produced the result — it surfaces the
    silent ``HeuristicDemandModel`` fallback when xgboost/torch aren't installed.
    """
    interventions = list(interventions or [])
    tc = normalize_time_context({**(time_context or {}), "weather": "clear"})
    key = _cache_key(model_kind, tc, interventions)

    cached = _cache_get(state, key)
    if cached is not None:
        return {**cached, "cached": True}

    # Collapse concurrent identical requests onto one computation (mirrors the
    # demo_locks double-checked-lock in api/app.py).
    lock = _key_lock(state, key)
    with lock:
        cached = _cache_get(state, key)
        if cached is not None:
            return {**cached, "cached": True}
        # Residual closure-GNN edit path. INERT by default: only entered when the
        # app-local gate ships closures AND torch+a checkpoint are present AND the
        # edit is closures-only (see residual_edit.should_use_residual). On any
        # failure it falls back to the identical sim path below.
        if residual_edit.should_use_residual(interventions):
            residual = _run_residual(state, model_kind, tc, interventions, iterations)
            if residual is not None:
                _cache_put(state, key, residual)
                return {**residual, "cached": False}
        result = _run(state, model_kind, tc, interventions, iterations)
        _cache_put(state, key, result)
        return {**result, "cached": False}


def _run(state, model_kind: str, tc: dict, interventions: List[dict], iterations: int) -> dict:
    model = load_demand_model(kind=model_kind)
    model_actual = _model_label(model)
    demand = predict_node_demand(state.graph, model, tc)

    surge_ops = [iv for iv in interventions if iv.get("op") == "demand_change"]
    graph_ops = [iv for iv in interventions if iv.get("op") in _GRAPH_OPS]

    grounded = build_grounded_od(state.graph, demand, tc, max_pairs=3000)
    od = grounded["od"]

    # Surges edit the OD AFTER grounding (auto_calibrate is off downstream) so
    # injected trips survive into the assignment instead of being normalized away.
    if surge_ops:
        od = apply_od_changes(state.graph, od, surge_ops)

    result = simulate_scenario(
        state.graph,
        od,
        graph_ops,
        iterations=iterations,
        weather="clear",
        time_context=tc,
        engine="equilibrium",
        backend="scipy",
        congestion_model="bpr",
        recompute="full",
        rgap_target=1e-2,
        max_equilibrium_iter=30,
    )
    return {
        "records": edge_records(state, result["graph"]),
        "summary": result["summary"],
        "rgap": result.get("rgap"),
        "model_actual": model_actual,
    }


def _run_residual(
    state, model_kind: str, tc: dict, interventions: List[dict], iterations: int
) -> Optional[dict]:
    """Instant closure preview via the residual GNN, on top of the open-road sim.

    sim_open SOURCE: the model's ``sim_open`` channels are fed the APP's cached
    no-edit **sim** equilibrium solve (``recompute_scenario(..., interventions=[])``
    — itself cached), NOT Liron's pressure-GNN baseline. Each closure is then one
    GNN forward on top of that single open-road solve.

    SIM-AS-VERIFIER: the GNN output is an instant *preview*; the deterministic sim
    remains the source of truth and should still run to reconcile (async, or on
    commit) — the verdict's own gate metrics are computed from such held-out sim
    comparisons. While the gate is OFF this function is never reached, so the
    default behaviour is byte-identical to the sim path. Returns ``None`` on any
    error so the caller transparently falls back to the full sim.
    """
    try:
        # The open-road baseline is the no-edit sim solve for this (model, tc).
        # Routed back through recompute_scenario so it shares the LRU cache and the
        # per-key lock (computed once, reused across every closure on this view).
        baseline = recompute_scenario(
            state,
            model_kind=model_kind,
            time_context=tc,
            interventions=[],
            iterations=iterations,
        )
        records = residual_edit.predict_closure_records(
            state,
            baseline["records"],
            interventions=interventions,
            time_context=tc,
        )
        summary = dict(baseline.get("summary") or {})
        summary["predictor"] = "residual_gnn"
        return {
            "records": records,
            "summary": summary,
            "rgap": None,
            "model_actual": baseline.get("model_actual"),
            "predictor": "residual_gnn",
            "verified": False,  # sim-as-verifier reconciliation not yet run
        }
    except Exception:
        return None


# ── cache plumbing ───────────────────────────────────────────────────────────


def _model_label(model) -> str:
    if isinstance(model, dict):
        return str(model.get("kind") or "")
    return type(model).__name__


def _round(v, n: int = 6):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return v


def _canonical_interventions(interventions: List[dict]) -> tuple:
    """Order-independent, float-jitter-stable signature of the modifications."""
    items = []
    for iv in interventions or []:
        d = {k: v for k, v in iv.items() if v is not None}
        for k in ("amount", "lng", "lat", "multiplier"):
            if k in d:
                d[k] = _round(d[k])
        if isinstance(d.get("directions"), list):
            d["directions"] = sorted(d["directions"])
        items.append(json.dumps(d, sort_keys=True, default=str))
    return tuple(sorted(items))


def _cache_key(model_kind: str, tc: dict, interventions: List[dict]) -> tuple:
    return (
        str(model_kind),
        (int(tc["hour"]), int(tc["day_of_week"]), int(tc["month"]), str(tc["weather"])),
        _canonical_interventions(interventions),
    )


def cache_key(
    model_kind: str, time_context: Optional[dict], interventions: Optional[List[dict]]
) -> tuple:
    """Public: the cache key for a raw (un-normalized) request — used by the
    prewarm manager to track/cancel in-flight warms and skip cached combos."""
    tc = normalize_time_context({**(time_context or {}), "weather": "clear"})
    return _cache_key(model_kind, tc, interventions or [])


def is_cached(state, key) -> bool:
    """Public: whether a combo (by ``cache_key``) is already in the LRU."""
    with state._cache_lock:
        return key in state._recompute_cache


def _cache_get(state, key):
    with state._cache_lock:
        result = state._recompute_cache.get(key)
        if result is not None:
            state._recompute_cache.move_to_end(key)
        return result


def _cache_put(state, key, result) -> None:
    with state._cache_lock:
        state._recompute_cache[key] = result
        state._recompute_cache.move_to_end(key)
        while len(state._recompute_cache) > _CACHE_MAX:
            old_key, _ = state._recompute_cache.popitem(last=False)
            state._recompute_locks.pop(old_key, None)


def _key_lock(state, key):
    with state._cache_lock:
        lock = state._recompute_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            state._recompute_locks[key] = lock
        return lock
