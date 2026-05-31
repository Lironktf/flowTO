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

import numpy as np

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


def _zscore_cols(t, cols):  # standardize selected channel columns across [S, E]
    import torch

    block = t[:, :, cols]
    mean = block.mean(dim=(0, 1), keepdim=True)
    std = block.std(dim=(0, 1), keepdim=True)
    std = torch.where(std > 0, std, torch.ones_like(std))
    t[:, :, cols] = (block - mean) / std
    return t


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

    scenario_attr = _zscore_cols(torch.stack(attrs), cols=[static_ea.shape[1] + 2, static_ea.shape[1] + 3])
    return {
        "x": x,
        "edge_index": static["edge_index"],
        "scenario_attr": scenario_attr,           # [S, E, lean_edge + 4]
        "targets": torch.stack(targets),          # [S, E]
        "context": torch.zeros(static_ea.shape[0], 2),  # no time context for sim pairs
        "node_in_dim": int(x.shape[1]),
        "edge_in_dim": int(scenario_attr.shape[2]),
        "context_in_dim": 2,
        "edge_order": edge_order,
    }
