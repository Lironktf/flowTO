"""P13 §C — assemble GNN training tensors from scenario-generator pairs.

Reuses Liron's static node/edge feature builder, drops the dead-weight columns
(``research/08`` lean set: keep ``lat/lon`` + structural, drop ``degree`` /
``distance_to_downtown`` / ``road_class_rank`` / ``from/to_node_degree`` /
``pagerank``), and appends the per-scenario channels the residual model needs:

  intervention_mask · capacity_mult · sim_open_load · sim_open_pressure

The target is the residual **Δpressure = delta_flow / capacity**. The per-scenario
channel logic is pure NumPy (torch-free, locally testable); the tensor assembly
lazy-imports torch + the baseline builder for the GB10.
See ``docs/specs/13-feedback-loop.md`` §C.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pandas only used in a lazy (string) type annotation below
    import pandas as pd

LEAN_NODE_DROP = {"degree", "distance_to_downtown_km", "pagerank"}
LEAN_EDGE_DROP = {"road_class_rank", "from_node_degree", "to_node_degree"}
SCENARIO_CHANNELS = ["intervention_mask", "capacity_mult", "sim_open_load", "sim_open_pressure"]


def scenario_edge_channels(
    scn_pairs: dict, edge_order: list[str], capacity: dict, *, capacity_up: float = 1.5
) -> tuple[np.ndarray, np.ndarray]:
    """Per-edge scenario channels + residual target for one scenario.

    ``scn_pairs``: ``{edge_id: (sign, closed_edge, sim_open, delta_flow)}``.
    Returns ``(channels [E,4], target [E])`` where target = delta_flow / capacity
    (Δpressure). Edges absent from the scenario stay zero.
    """
    e = len(edge_order)
    mask = np.zeros(e)
    cmult = np.ones(e)
    sim_open = np.zeros(e)
    sim_press = np.zeros(e)
    target = np.zeros(e)
    for i, eid in enumerate(edge_order):
        if eid not in scn_pairs:
            continue
        sign, closed, so, dflow = scn_pairs[eid]
        cap = max(float(capacity.get(eid, 1.0)), 1.0)
        sim_open[i] = so
        sim_press[i] = so / cap
        target[i] = dflow / cap
        if eid == closed:
            mask[i] = 1.0
            cmult[i] = 0.0 if sign == "closure" else capacity_up
    return np.stack([mask, cmult, sim_open, sim_press], axis=1), target


def _standardize_simopen(t, cols, stats=None):
    """Z-score the sim_open channel columns across [S, E].

    Computes the mean/std when ``stats`` is None (Stage-1), or **reuses** the saved
    Stage-1 stats (Stage-2 warm-start) so the fine-tune sees the same input scaling
    the pre-trained weights expect. Returns ``(tensor, stats)``.
    """
    import torch

    block = t[:, :, cols]
    if stats is None:
        mean = block.mean(dim=(0, 1), keepdim=True)
        std = block.std(dim=(0, 1), keepdim=True)
        std = torch.where(std > 0, std, torch.ones_like(std))
        stats = {"mean": mean, "std": std}
    t[:, :, cols] = (block - stats["mean"]) / stats["std"]
    return t, stats


def build_stage1_tensors(graph, pairs: pd.DataFrame) -> dict:  # pragma: no cover - torch on GB10
    """Full Stage-1 tensors: lean static features + per-scenario channels + targets."""
    import torch

    from models.gnn.build_gnn_dataset import _build_static_tensors
    from models.gnn.utils import EDGE_FEATURE_NAMES, NODE_FEATURE_NAMES, fit_standardizer

    static = _build_static_tensors(graph, use_pagerank=False)
    node_keep = [i for i, n in enumerate(NODE_FEATURE_NAMES) if n not in LEAN_NODE_DROP]
    edge_keep = [i for i, n in enumerate(EDGE_FEATURE_NAMES) if n not in LEAN_EDGE_DROP]

    x_raw = static["x_raw"][:, node_keep]
    ea_raw = static["edge_attr_raw"][:, edge_keep]
    ns, es = fit_standardizer(x_raw), fit_standardizer(ea_raw)
    x = (x_raw - ns["mean"]) / ns["std"]
    static_ea = (ea_raw - es["mean"]) / es["std"]

    meta = static["edge_meta"]
    edge_order = [m["edge_id"] for m in meta]
    capacity = {m["edge_id"]: m["capacity"] for m in meta}

    attrs, targets = [], []
    for _sid, grp in pairs.groupby("scenario_id"):
        scn = {
            r["edge_id"]: (r["sign"], r["closed_edge"], r["sim_open"], r["delta_flow"])
            for _, r in grp.iterrows()
        }
        chan, tgt = scenario_edge_channels(scn, edge_order, capacity)
        attrs.append(torch.cat([static_ea, torch.tensor(chan, dtype=torch.float32)], dim=1))
        targets.append(torch.tensor(tgt, dtype=torch.float32))

    simopen_cols = [static_ea.shape[1] + 2, static_ea.shape[1] + 3]
    scenario_attr, simopen_stats = _standardize_simopen(torch.stack(attrs), simopen_cols)
    return {
        "x": x,
        "edge_index": static["edge_index"],
        "scenario_attr": scenario_attr,  # [S, E, lean_edge + 4]
        "targets": torch.stack(targets),  # [S, E]
        "context": torch.zeros(static_ea.shape[0], 2),  # no time context for sim pairs
        "node_in_dim": int(x.shape[1]),
        "edge_in_dim": int(scenario_attr.shape[2]),
        "context_in_dim": 2,
        "edge_order": edge_order,
        # persisted so the Stage-2 fine-tune reuses the same input scaling
        "standardizers": {"node": ns, "edge_static": es, "simopen": simopen_stats},
    }


def build_stage2_tensors(
    graph, residuals, sim_open_full, *, standardizers=None
):  # pragma: no cover - torch on GB10
    """Stage-2 tensors from **real-closure** residual rows (one scenario per closure).

    Channels mirror Stage-1 exactly so a Stage-1 warm-start applies cleanly: lean
    static edge features + intervention mask/cmult at the closed edge + ``sim_open``
    load/pressure for **all** edges from the single global open solve
    (``sim_open_full``). Targets = ``r_obs / capacity`` (the real Δpressure) **only**
    at observed sites; ``obs_mask`` marks them so the loss never trains on the
    unmeasured edges (no fabricated zeros). When ``standardizers`` from the Stage-1
    checkpoint are passed, the static + sim_open scalings are reused (not refit).

    ``residuals``: the frame from ``real_residuals.build_real_residuals`` — needs
    ``ID``, ``edge_id``, ``closed_edge``, ``r_obs``, ``split``, ``StartTime``.
    Returns the Stage-1 keys plus ``obs_mask`` [S,E], ``capacity`` [E],
    ``scenario_ids``, ``splits``, ``start_times``.
    """
    import torch

    from models.gnn.build_gnn_dataset import _build_static_tensors
    from models.gnn.utils import EDGE_FEATURE_NAMES, NODE_FEATURE_NAMES, fit_standardizer

    static = _build_static_tensors(graph, use_pagerank=False)
    node_keep = [i for i, n in enumerate(NODE_FEATURE_NAMES) if n not in LEAN_NODE_DROP]
    edge_keep = [i for i, n in enumerate(EDGE_FEATURE_NAMES) if n not in LEAN_EDGE_DROP]

    x_raw = static["x_raw"][:, node_keep]
    ea_raw = static["edge_attr_raw"][:, edge_keep]
    if standardizers:
        ns, es = standardizers["node"], standardizers["edge_static"]
        simopen_stats = standardizers.get("simopen")
    else:
        ns, es = fit_standardizer(x_raw), fit_standardizer(ea_raw)
        simopen_stats = None
    x = (x_raw - ns["mean"]) / ns["std"]
    static_ea = (ea_raw - es["mean"]) / es["std"]

    meta = static["edge_meta"]
    edge_order = [m["edge_id"] for m in meta]
    capacity = {m["edge_id"]: m["capacity"] for m in meta}
    cap_vec = np.array([max(float(capacity.get(e, 1.0)), 1.0) for e in edge_order])

    attrs, targets, masks, ids, splits, times = [], [], [], [], [], []
    for iv_id, grp in residuals.groupby("ID"):
        closed = grp["closed_edge"].iloc[0]
        robs = {r["edge_id"]: float(r["r_obs"]) for _, r in grp.iterrows()}
        # every edge gets its global open flow; only observed edges get a target
        scn = {
            e: ("closure", closed, float(sim_open_full.get(e, 0.0)), robs.get(e, 0.0))
            for e in edge_order
        }
        chan, tgt = scenario_edge_channels(scn, edge_order, capacity)
        omask = np.array([1.0 if e in robs else 0.0 for e in edge_order])
        attrs.append(torch.cat([static_ea, torch.tensor(chan, dtype=torch.float32)], dim=1))
        targets.append(torch.tensor(tgt, dtype=torch.float32))
        masks.append(torch.tensor(omask, dtype=torch.float32))
        ids.append(iv_id)
        splits.append(grp["split"].iloc[0])
        times.append(grp["StartTime"].iloc[0])

    scenario_attr = torch.stack(attrs)
    simopen_cols = [static_ea.shape[1] + 2, static_ea.shape[1] + 3]
    scenario_attr, simopen_stats = _standardize_simopen(scenario_attr, simopen_cols, simopen_stats)
    return {
        "x": x,
        "edge_index": static["edge_index"],
        "scenario_attr": scenario_attr,  # [S, E, lean_edge + 4]
        "targets": torch.stack(targets),  # [S, E] (Δpressure; valid where obs_mask)
        "obs_mask": torch.stack(masks),  # [S, E] 1 at observed sites
        "context": torch.zeros(static_ea.shape[0], 2),
        "capacity": torch.tensor(cap_vec, dtype=torch.float32),  # [E] flow⇄pressure
        "node_in_dim": int(x.shape[1]),
        "edge_in_dim": int(scenario_attr.shape[2]),
        "context_in_dim": 2,
        "edge_order": edge_order,
        "scenario_ids": ids,
        "splits": splits,
        "start_times": times,
        "standardizers": {"node": ns, "edge_static": es, "simopen": simopen_stats},
    }
