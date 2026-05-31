"""P13 §D — the activation gate.

Ship the GNN **only if** its residual error beats the deterministic sim's on
held-out **real** interventions. Compares ``r_gnn`` (the GNN's predicted residual)
and ``r_sim`` (the sim's own residual, ``sim_int − sim_open``) against ``r_obs``
(the real residual, ``observed − sim_open``) — lower RMSE wins, with a margin ``eps``
and a minimum-n guard. Also reports a rank / top-K impacted-edge metric (what the
optimizer consumes). If the GNN doesn't beat the sim, the sim stays the predictor —
a correct outcome, reported honestly. See ``docs/specs/13-feedback-loop.md`` §D.
"""

from __future__ import annotations

import numpy as np

from .benchmark.metrics import mae, rank_topk_overlap, rmse


def activation_gate(
    r_obs, r_gnn, r_sim, *, eps: float = 0.0, min_n: int = 10, topk: int = 10
) -> dict:
    """Decide whether to ship the GNN over the sim on held-out real residuals."""
    r_obs = np.asarray(r_obs, dtype=np.float64)
    r_gnn = np.asarray(r_gnn, dtype=np.float64)
    r_sim = np.asarray(r_sim, dtype=np.float64)
    n = int(r_obs.size)

    err_gnn, err_sim = rmse(r_gnn, r_obs), rmse(r_sim, r_obs)
    ship = bool(n >= min_n and err_gnn < err_sim - eps)
    return {
        "n": n,
        "err_gnn_rmse": err_gnn,
        "err_sim_rmse": err_sim,
        "mae_gnn": mae(r_gnn, r_obs),
        "mae_sim": mae(r_sim, r_obs),
        "rank_gnn": rank_topk_overlap(r_gnn, r_obs, topk),
        "rank_sim": rank_topk_overlap(r_sim, r_obs, topk),
        "improvement_rmse": err_sim - err_gnn,
        "ship": ship,
        "verdict": "ship GNN" if ship else "keep sim",
    }
