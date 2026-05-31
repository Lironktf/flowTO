"""P13 §C — residual trainer (Stage-1 sim pre-train; Stage-2 fine-tune is the same
loop warm-started on the P14 real residuals).

Stage-1 teaches the GNN to reproduce the sim's reroute residual from unlimited
scenario-generator pairs. The bar it must clear is the **zero-predictor**
(``mean|target|``) — i.e. the GNN must explain the residual better than predicting
"no change". See ``docs/specs/13-feedback-loop.md`` §C.
"""

from __future__ import annotations

import numpy as np


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

    return {
        "n_scenarios": int(n),
        "n_train": len(tr_idx),
        "n_val": len(val_idx),
        "val_mae_all": mae(val_idx),
        "zero_val_mae_all": zero_mae(val_idx),
        "val_mae_affected": mae(val_idx, affected_only=True),
        "zero_val_mae_affected": zero_mae(val_idx, affected_only=True),
        "device": str(device),
    }
