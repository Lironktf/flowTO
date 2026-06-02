"""Residual closure-GNN edit path — the third compute path (P13 §C/§D wiring).

This is the *edit* analogue of ``api/gnn_baseline.py``. Where the baseline GNN
makes the no-edit "usual congestion" view instant, this module makes a **closure**
edit instant: instead of re-running the equilibrium engine (~50s in
``api/recompute.py``) for every closed road, it predicts a per-edge **Δpressure**
residual on top of an already-computed open-road sim solve and applies it.

    cached open-road sim baseline (Record5)        ← the APP's no-edit sim solve
      + closure interventions + time_context
        → scenario_edge_channels (saved standardizers, never refit)
          → one ResidualEdgePredictor forward → per-edge Δpressure
            → × capacity = Δflow → applied to the baseline load/pressure
              → Record5 tuples the renderer already consumes

GATE — OFF BY DEFAULT.  This path is INERT until two things are true:
  1. ``api/gate_verdict.json`` (the app-local gate) flips ``closures.ship`` to
     ``true`` — it ships ``false`` because we have NOT validated that the model's
     ``sim_open`` channels (which it was trained on a ~1500-pair grounded OD)
     transfer to the APP's open-road equilibrium baseline; and
  2. a validated checkpoint is present at ``TS_RESIDUAL_CKPT``
     (default ``models/gnn/stage2_residual.pt``).
The dispatch in ``api/recompute.py`` checks the gate + torch importability +
op scope, and falls back to the deterministic sim on ANY of: gate off, no torch,
missing/corrupt checkpoint, non-closure op, or an inference error. So the default
behaviour is byte-identical to today's sim path.

sim_open SOURCING — CRITICAL.  The model's ``sim_open_load`` / ``sim_open_pressure``
edge channels must be the APP's open-road **sim** solve (the cached no-edit
equilibrium baseline), NOT Liron's pressure-GNN baseline (a different quantity →
garbage in). The caller passes that baseline in as ``baseline_records`` (the
Record5 list from a no-edit ``recompute_scenario`` solve, cached once); per closure
this module is a single GNN forward on top of it. See ``predict_closure_records``.

Like ``gnn_baseline.py`` the heavy checkpoint bundle is loaded ONCE (module cache)
on the inference device and reused across closures.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

# App-local activation gate. Defaults to ship=false. Override the file location
# with TS_RESIDUAL_GATE (else the JSON next to this module). Read fresh each
# dispatch (cheap) so a verdict can be dropped in without a restart.
_DEFAULT_GATE_REL = os.path.join(os.path.dirname(__file__), "gate_verdict.json")

# Default checkpoint location; override with the TS_RESIDUAL_CKPT env var. The
# default mirrors the artifact shipped under models/gnn/. Resolved relative to the
# repo root when not absolute.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_DEFAULT_CKPT_REL = os.path.join("models", "gnn", "stage2_residual.pt")

_bundle = None
_bundle_lock = threading.Lock()


# ── activation gate (app-local verdict) ────────────────────────────────────── #


def gate_path() -> str:
    """Resolve the app-local gate-verdict path (env ``TS_RESIDUAL_GATE`` or default)."""
    p = os.environ.get("TS_RESIDUAL_GATE", "").strip()
    return p if p else _DEFAULT_GATE_REL


def gate_ship_closures() -> bool:
    """Whether the app-local gate says ship the residual GNN for closures.

    DEFAULTS TO FALSE on any of: missing file, malformed JSON, or
    ``closures.ship`` not explicitly ``true``. This is the single switch that
    flips the closure edit path from sim → GNN; it ships ``false``.
    """
    try:
        with open(gate_path()) as fh:
            verdict = json.load(fh)
        return bool(verdict.get("closures", {}).get("ship", False) is True)
    except Exception:
        return False


# ── checkpoint path / availability ─────────────────────────────────────────── #


def checkpoint_path() -> str:
    """Resolve the residual checkpoint path (env ``TS_RESIDUAL_CKPT`` or default)."""
    p = os.environ.get("TS_RESIDUAL_CKPT", "").strip() or _DEFAULT_CKPT_REL
    return p if os.path.isabs(p) else os.path.join(_REPO_ROOT, p)


def torch_available() -> bool:
    """Whether torch + torch-geometric (the GraphSAGE backbone) can be imported.

    The whole residual path is gated on this so a machine without the ``[gnn]``
    extra (CI / most laptops) never imports torch and always takes the sim path.
    """
    import importlib.util

    return (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("torch_geometric") is not None
    )


def checkpoint_present() -> bool:
    """Whether a checkpoint file exists at the configured path."""
    return os.path.exists(checkpoint_path())


# ── heavy bundle (loaded once, module-cached — mirrors gnn_baseline.get_bundle) ─ #


def get_bundle(graph) -> dict:
    """Load (once) the residual checkpoint + static graph tensors on the device.

    Returns a dict with the model, the standardized static node/edge tensors,
    ``edge_index``, ``edge_order`` (edge_id order aligned to the tensors),
    ``capacity`` (per edge), ``context_in_dim``, and the saved ``standardizers``.

    The static tensors are built ONCE for the live graph; the model is loaded with
    its SAVED standardizers (never refit). Heavy imports (torch, the feedback
    dataset builder, Liron's static-tensor builder) are lazy so a torch-free
    process can import this module without paying for them.
    """
    global _bundle
    if _bundle is not None and _bundle.get("graph_id") == id(graph):
        return _bundle
    with _bundle_lock:
        if _bundle is not None and _bundle.get("graph_id") == id(graph):
            return _bundle

        import torch

        from models.gnn.build_gnn_dataset import _build_static_tensors
        from models.gnn.utils import EDGE_FEATURE_NAMES, NODE_FEATURE_NAMES

        from ..feedback.dataset import LEAN_EDGE_DROP, LEAN_NODE_DROP
        from ..feedback.train_residual import load_checkpoint

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, ck = load_checkpoint(checkpoint_path(), device=device)
        model = model.to(device).eval()
        stds = ck["standardizers"]

        # Lean static features — must match the trainer's feature set exactly so the
        # saved standardizers + learned weights line up.
        static = _build_static_tensors(graph, use_pagerank=False)
        node_keep = [i for i, n in enumerate(NODE_FEATURE_NAMES) if n not in LEAN_NODE_DROP]
        edge_keep = [i for i, n in enumerate(EDGE_FEATURE_NAMES) if n not in LEAN_EDGE_DROP]
        x_raw = static["x_raw"][:, node_keep]
        ea_raw = static["edge_attr_raw"][:, edge_keep]
        ns, es = stds["node"], stds["edge_static"]
        x = ((x_raw - ns["mean"]) / ns["std"]).to(device)
        static_ea = ((ea_raw - es["mean"]) / es["std"]).to(device)

        meta = static["edge_meta"]
        edge_order = [m["edge_id"] for m in meta]
        capacity = {m["edge_id"]: max(float(m.get("capacity") or 0.0), 1.0) for m in meta}

        _bundle = {
            "graph_id": id(graph),
            "device": device,
            "model": model,
            "x": x,
            "edge_index": static["edge_index"].to(device),
            "static_ea": static_ea,  # [E, lean_edge] standardized static edge feats
            "edge_order": edge_order,  # edge_id per tensor row
            "capacity": capacity,  # edge_id -> capacity (>=1)
            "context_in_dim": int(ck["context_in_dim"]),
            "simopen_stats": stds.get("simopen"),
            "checkpoint": ck,
        }
        return _bundle


# ── inference: closure → per-edge Δpressure → Record5 ──────────────────────── #


def _closed_edge_ids(interventions, graph=None) -> list:
    """Edge ids closed by closure ops.

    ``close_edge`` / ``remove_edge`` name a graph edge directly. ``close_node`` (a
    blocked intersection) names a node — it is expanded here into EVERY edge
    incident to that node, which needs the live ``graph``. Without a graph,
    ``close_node`` ops are skipped (the sim path handles them instead).
    """
    out = []
    for iv in interventions or []:
        op = iv.get("op")
        if op in ("close_edge", "remove_edge"):
            eid = iv.get("edge_id")
            if eid is not None:
                out.append(eid)
        elif op == "close_node" and graph is not None:
            node_id = iv.get("node_id")
            if node_id is None:
                continue
            from ..graph.mutations import incident_edge_ids

            try:
                out.extend(incident_edge_ids(graph, node_id))
            except KeyError:
                pass  # unknown node → nothing to close (sim would raise; we no-op)
    return out


def predict_closure_records(
    state,
    baseline_records,
    *,
    interventions,
    time_context: Optional[dict] = None,
) -> list:
    """Predict Record5 tuples for a closure scenario via the residual GNN.

    ``baseline_records``: the APP's cached **open-road sim** solve as Record5 tuples
    ``(edge_idx, load, speed, pressure, closure)`` (from a no-edit
    ``recompute_scenario``). This is the ``sim_open`` source — the SIM baseline, not
    Liron's pressure GNN. ``interventions`` should already be filtered to closures by
    the caller; closed edges are read from ``close_edge`` / ``remove_edge`` ops.
    ``time_context`` is accepted for forward-compatibility; the current checkpoint
    has no time context (``context_in_dim == 2`` zeros), so it is not consumed yet.

    Returns Record5 tuples for every edge present in ``baseline_records``: the closed
    edge(s) forced to closure=1 with zero load/speed, every other edge's
    open-road load/pressure shifted by ``Δpressure × capacity`` (clamped at 0).
    """
    from ..feedback.dataset import scenario_edge_channels

    b = get_bundle(state.graph)
    edge_order = b["edge_order"]
    capacity = b["capacity"]

    # Map tensor-row edge_id -> the renderer's edge_idx (state.edge_index), and the
    # open-road sim load by edge_id from the cached baseline (sim_open channel).
    idx_to_eid = {i: eid for eid, i in state.edge_index.items()}
    sim_open_by_eid: dict = {}
    for rec in baseline_records:
        edge_idx, load = int(rec[0]), float(rec[1])
        eid = idx_to_eid.get(edge_idx)
        if eid is not None:
            sim_open_by_eid[eid] = load

    closed = set(_closed_edge_ids(interventions, graph=state.graph))
    # Pick the closed edge for the channel builder. The trainer keys one closure per
    # scenario; for multi-edge closures we feed the mask for all closed edges (the
    # channel builder only marks the single ``closed`` arg, so we set the mask after).
    closed_for_builder = next(iter(closed), None)

    scn = {
        eid: ("closure", closed_for_builder, sim_open_by_eid.get(eid, 0.0), 0.0)
        for eid in edge_order
    }
    chan, _tgt = scenario_edge_channels(scn, edge_order, capacity)  # [E,4] numpy

    # Mark every closed edge (channel builder only marked closed_for_builder).
    for i, eid in enumerate(edge_order):
        if eid in closed:
            chan[i, 0] = 1.0  # intervention_mask
            chan[i, 1] = 0.0  # capacity_mult (fully closed)

    # One forward pass → per-edge signed Δpressure. All torch lives in
    # ``model_forward`` (assembles [static · channels], applies the SAVED sim_open
    # standardizer — never refit — and runs the model). Keeping this function
    # numpy-only makes it unit-testable with a fake bundle on a torch-free box.
    dpress = model_forward(b, chan)  # numpy [E] signed Δpressure

    # Apply Δpressure to the open-road baseline → new load/pressure → Record5.
    speed_by_idx = {int(r[0]): float(r[2]) for r in baseline_records}
    base_press_by_eid = {}
    for rec in baseline_records:
        eid = idx_to_eid.get(int(rec[0]))
        if eid is not None:
            base_press_by_eid[eid] = float(rec[3])

    recs = []
    for i, eid in enumerate(edge_order):
        idx = state.edge_index.get(eid)
        if idx is None:
            continue
        cap = capacity[eid]
        if eid in closed:
            recs.append((idx, 0.0, 0.0, 0.0, 1))
            continue
        open_load = sim_open_by_eid.get(eid, 0.0)
        open_press = base_press_by_eid.get(eid, open_load / cap)
        new_press = max(open_press + float(dpress[i]), 0.0)
        new_load = max(open_load + float(dpress[i]) * cap, 0.0)
        spd = speed_by_idx.get(idx, 0.0)
        recs.append((idx, new_load, spd, new_press, 0))
    # Preserve any baseline edges not in the tensor edge_order (defensive: keep the
    # renderer's edge set stable / identical coverage to the sim path).
    covered = {state.edge_index.get(eid) for eid in edge_order}
    for rec in baseline_records:
        if int(rec[0]) not in covered:
            recs.append(tuple(rec))
    return recs


def model_forward(bundle: dict, chan):
    """One ResidualEdgePredictor forward over all edges → numpy Δpressure [E].

    Takes the numpy per-scenario channels ``chan`` [E,4], assembles the edge-feature
    tensor (standardized static features · channels), applies the SAVED sim_open
    standardizer to the two sim_open columns (never refit), and runs one forward.
    Isolated here so the rest of the path stays torch-free and testable.
    """
    import torch

    device = bundle["device"]
    static_ea = bundle["static_ea"]
    n_static = static_ea.shape[1]
    chan_t = torch.tensor(chan, dtype=torch.float32, device=device)
    edge_attr = torch.cat([static_ea, chan_t], dim=1)
    simopen_stats = bundle.get("simopen_stats")
    if simopen_stats is not None:
        cols = [n_static + 2, n_static + 3]  # sim_open_load, sim_open_pressure
        mean = simopen_stats["mean"].to(device).reshape(-1)
        std = simopen_stats["std"].to(device).reshape(-1)
        edge_attr[:, cols] = (edge_attr[:, cols] - mean) / std
    ctx = torch.zeros(bundle["x"].shape[0], bundle["context_in_dim"], device=device)
    with torch.no_grad():
        out = bundle["model"](bundle["x"], bundle["edge_index"], edge_attr, ctx)
    return out.detach().cpu().numpy()


def reset_cache() -> None:
    """Drop the module-cached bundle (tests / checkpoint hot-swap)."""
    global _bundle
    with _bundle_lock:
        _bundle = None


# ── dispatch decision (used by api/recompute.py) ───────────────────────────── #

# Closure ops the residual path is scoped to. ``close_node`` (a blocked
# intersection) is expanded into its incident-edge closures at inference time (see
# _closed_edge_ids), so the per-edge model handles it as a multi-edge closure.
# Everything else — reopen_edge, demand_change, change_capacity, add_edge — STAYS
# on the sim.
CLOSURE_OPS = {"close_edge", "remove_edge", "close_node"}


def is_closure_scope(interventions) -> bool:
    """True iff there is >=1 intervention and EVERY one is a closure op.

    A mixed edit (e.g. a closure plus a demand surge, or a closure plus a reopen)
    is out of scope → the sim handles the whole scenario, so the preview stays a
    single consistent solve.
    """
    ivs = list(interventions or [])
    if not ivs:
        return False
    return all(iv.get("op") in CLOSURE_OPS for iv in ivs)


def should_use_residual(interventions) -> bool:
    """Whether the residual GNN closure path should be taken for this edit.

    ALL must hold (else → sim path, unchanged): the app-local gate ships closures,
    torch+PyG are importable, a checkpoint exists, and the op set is closures-only.
    Defaults to ``False`` (sim) on every other case. This is the single chokepoint
    ``api/recompute.py`` consults; with the shipped gate it always returns ``False``.
    """
    return (
        is_closure_scope(interventions)
        and gate_ship_closures()
        and checkpoint_present()
        and torch_available()
    )
