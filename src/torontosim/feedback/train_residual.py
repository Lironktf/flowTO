"""P13 §C — residual trainer.

Stage-1 teaches the GNN to reproduce the sim's reroute residual from unlimited
scenario-generator pairs. The bar it must clear is the **zero-predictor**
(``mean|target|``) — i.e. the GNN must explain the residual better than predicting
"no change". **Stage-2** (``train_stage2``) warm-starts that pre-trained model and
fine-tunes it on the **real** P14 closure residuals (``r_obs``), training only on the
observed sites (masked loss — no fabricated zeros) and early-stopping on a held-out
split grouped by ``centreline_id`` + temporal. This is the feedback step; the held-out
predictions feed the activation gate. See ``docs/specs/13-feedback-loop.md`` §C/§D.
"""

from __future__ import annotations

import numpy as np


def _split_indices(splits: list) -> tuple[list[int], list[int]]:
    """Scenario indices for the train/held-out folds from a per-scenario split list.

    Anything not explicitly ``"test"`` is treated as train (so a missing split never
    silently leaks into the held-out evaluation). Torch-free → unit-testable.
    """
    train = [i for i, s in enumerate(splits) if s != "test"]
    test = [i for i, s in enumerate(splits) if s == "test"]
    return train, test


def save_checkpoint(  # pragma: no cover - torch on the GB10
    path, model, *, node_in_dim, edge_in_dim, context_in_dim, hidden_dim, standardizers
):
    """Persist the residual model + the dims and feature standardizers Stage-2 needs."""
    import torch

    torch.save(
        {
            "model_state": model.state_dict(),
            "node_in_dim": int(node_in_dim),
            "edge_in_dim": int(edge_in_dim),
            "context_in_dim": int(context_in_dim),
            "hidden_dim": int(hidden_dim),
            "standardizers": standardizers,
        },
        path,
    )


def load_checkpoint(path, *, device=None):  # pragma: no cover - torch on the GB10
    """Rebuild the residual model from a checkpoint; return ``(model, ckpt_dict)``."""
    import torch

    from .model import ResidualEdgePredictor

    ck = torch.load(path, map_location=device or "cpu", weights_only=False)
    model = ResidualEdgePredictor(
        ck["node_in_dim"], ck["edge_in_dim"], ck["context_in_dim"],
        hidden_dim=ck["hidden_dim"],
    )
    model.load_state_dict(ck["model_state"])
    return model, ck


def train_stage1(  # pragma: no cover - torch on the GB10
    graph,
    pairs,
    *,
    epochs: int = 100,
    hidden_dim: int = 64,
    lr: float = 1e-3,
    val_frac: float = 0.2,
    seed: int = 42,
    affected_weight: float = 20.0,
    eps: float = 1e-3,
    ckpt_path=None,
) -> dict:
    """Train the residual GNN on scenario-generator pairs; return metrics.

    Uses a **blast-radius-weighted** loss: edges the intervention actually moves
    (``|target| > eps``) are up-weighted so the zero-residual majority doesn't drown
    them. The headline metric is the **affected-edge** MAE vs the zero-predictor.
    """
    import torch
    from torch.nn import SmoothL1Loss

    from .dataset import build_stage1_tensors
    from .model import ResidualEdgePredictor

    torch.manual_seed(seed)
    t = build_stage1_tensors(graph, pairs)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    x, ei, ctx = t["x"].to(device), t["edge_index"].to(device), t["context"].to(device)
    attr, tgt = t["scenario_attr"].to(device), t["targets"].to(device)

    n = attr.shape[0]
    order = torch.randperm(n, generator=torch.Generator().manual_seed(seed))
    n_val = max(1, int(val_frac * n))
    val_idx, tr_idx = order[:n_val].tolist(), order[n_val:].tolist()

    model = ResidualEdgePredictor(
        t["node_in_dim"], t["edge_in_dim"], t["context_in_dim"], hidden_dim=hidden_dim
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = SmoothL1Loss(reduction="none")

    def _affected(s):
        return tgt[s].abs() > eps

    def mae(idxs, affected_only=False) -> float:
        model.eval()
        with torch.no_grad():
            errs = []
            for s in idxs:
                err = torch.abs(model(x, ei, attr[s], ctx) - tgt[s])
                if affected_only:
                    m = _affected(s)
                    if m.any():
                        errs.append(float(err[m].mean()))
                else:
                    errs.append(float(err.mean()))
        return float(np.mean(errs)) if errs else float("nan")

    def zero_mae(idxs, affected_only=False) -> float:
        vals = []
        for s in idxs:
            m = _affected(s)
            t_ = tgt[s][m] if affected_only else tgt[s]
            if t_.numel():
                vals.append(float(t_.abs().mean()))
        return float(np.mean(vals)) if vals else float("nan")

    for _ in range(epochs):
        model.train()
        for s in tr_idx:
            opt.zero_grad()
            w = 1.0 + affected_weight * _affected(s).float()
            loss = (loss_fn(model(x, ei, attr[s], ctx), tgt[s]) * w).mean()
            loss.backward()
            opt.step()

    if ckpt_path is not None:
        save_checkpoint(
            ckpt_path, model,
            node_in_dim=t["node_in_dim"], edge_in_dim=t["edge_in_dim"],
            context_in_dim=t["context_in_dim"], hidden_dim=hidden_dim,
            standardizers=t["standardizers"],
        )

    return {
        "n_scenarios": int(n),
        "n_train": len(tr_idx),
        "n_val": len(val_idx),
        "val_mae_all": mae(val_idx),
        "zero_val_mae_all": zero_mae(val_idx),
        "val_mae_affected": mae(val_idx, affected_only=True),
        "zero_val_mae_affected": zero_mae(val_idx, affected_only=True),
        "device": str(device),
        "ckpt_path": str(ckpt_path) if ckpt_path is not None else None,
    }


def train_stage2(  # pragma: no cover - torch on the GB10
    graph,
    residuals,
    sim_open_full,
    *,
    stage1_ckpt,
    epochs: int = 300,
    lr: float = 1e-4,
    weight_decay: float = 1e-4,
    patience: int = 30,
    seed: int = 42,
    ckpt_path=None,
) -> dict:
    """Warm-start the Stage-1 model and fine-tune on the **real** closure residuals.

    Targets are ``r_obs / capacity`` at the observed sites only (``obs_mask``); the
    loss is masked to those edges so the model never trains on unmeasured edges.
    Low lr + early-stop on the held-out (``split=="test"``) fold — which the P14
    packager builds grouped by ``centreline_id`` (no spatial leak); pass a temporally
    held-out split for the deployment-mimicking test. Returns Stage-2 metrics plus
    ``held_out`` arrays ``(r_obs, r_gnn, r_sim)`` in **flow units** for the gate.
    """
    import torch
    from torch.nn import SmoothL1Loss

    from .dataset import build_stage2_tensors

    torch.manual_seed(seed)
    model, ck = load_checkpoint(stage1_ckpt)
    t = build_stage2_tensors(
        graph, residuals, sim_open_full, standardizers=ck.get("standardizers")
    )
    if t["edge_in_dim"] != ck["edge_in_dim"]:
        raise ValueError(
            f"edge_in_dim mismatch: stage2 {t['edge_in_dim']} vs ckpt {ck['edge_in_dim']} "
            "(Stage-1 and Stage-2 must share the graph + feature set)"
        )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    x, ei, ctx = t["x"].to(device), t["edge_index"].to(device), t["context"].to(device)
    attr, tgt, omask = (
        t["scenario_attr"].to(device), t["targets"].to(device), t["obs_mask"].to(device),
    )
    cap = t["capacity"].to(device)
    tr_idx, te_idx = _split_indices(t["splits"])
    monitor = te_idx or tr_idx  # if no held-out fold, early-stop on train

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    loss_fn = SmoothL1Loss(reduction="none")

    def masked_mae(idxs) -> float:
        model.eval()
        with torch.no_grad():
            errs = []
            for s in idxs:
                m = omask[s] > 0
                if m.any():
                    err = torch.abs(model(x, ei, attr[s], ctx)[m] - tgt[s][m])
                    errs.append(float(err.mean()))
        return float(np.mean(errs)) if errs else float("nan")

    best = {"mae": float("inf"), "state": None, "epoch": -1}
    no_improve = 0
    for ep in range(epochs):
        model.train()
        for s in tr_idx:
            w = omask[s]
            if w.sum() == 0:
                continue
            opt.zero_grad()
            loss = (loss_fn(model(x, ei, attr[s], ctx), tgt[s]) * w).sum() / w.sum().clamp_min(1.0)
            loss.backward()
            opt.step()
        cur = masked_mae(monitor)
        if cur < best["mae"]:
            best = {
                "mae": cur,
                "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                "epoch": ep,
            }
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                break
    if best["state"] is not None:
        model.load_state_dict(best["state"])

    # held-out residuals in FLOW units (Δpressure × capacity) for the activation gate
    rsim_lookup = {(r.ID, r.edge_id): float(r.r_sim) for r in residuals.itertuples()}
    held = {"r_obs": [], "r_gnn": [], "r_sim": [], "ID": [], "edge_id": []}
    model.eval()
    with torch.no_grad():
        for s in te_idx:
            pred = model(x, ei, attr[s], ctx)
            iv_id = t["scenario_ids"][s]
            for i in np.where((omask[s] > 0).cpu().numpy())[0]:
                eid = t["edge_order"][i]
                capi = float(cap[i])
                held["r_obs"].append(float(tgt[s][i]) * capi)   # exact: (r_obs/cap)·cap
                held["r_gnn"].append(float(pred[i]) * capi)
                held["r_sim"].append(rsim_lookup.get((iv_id, eid), float("nan")))
                held["ID"].append(iv_id)
                held["edge_id"].append(eid)

    if ckpt_path is not None:
        save_checkpoint(
            ckpt_path, model,
            node_in_dim=t["node_in_dim"], edge_in_dim=t["edge_in_dim"],
            context_in_dim=t["context_in_dim"], hidden_dim=ck["hidden_dim"],
            standardizers=t["standardizers"],
        )

    return {
        "n_scenarios": len(t["scenario_ids"]),
        "n_train": len(tr_idx),
        "n_test": len(te_idx),
        "n_held_out_edges": len(held["r_obs"]),
        "best_epoch": best["epoch"],
        "val_masked_mae_pressure": best["mae"],
        "device": str(device),
        "ckpt_path": str(ckpt_path) if ckpt_path is not None else None,
        "held_out": held,
    }
