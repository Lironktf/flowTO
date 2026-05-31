"""P13 §C — the closure/opening residual model.

Reuses Liron's ``GraphSAGEEdgePredictor`` backbone (node encoder + edge head) but
replaces the ``softplus`` output with an **identity** head, so the prediction is a
**signed residual** (Δpressure over the sim) rather than a non-negative pressure.
Closure conditioning + the ``sim_open`` baseline ride in via the edge feature vector
(see ``feedback/dataset.py``), so the topology is unchanged and one forward pass
scores any intervention.

See ``docs/specs/13-feedback-loop.md`` §C.
"""

from __future__ import annotations

import torch

from models.gnn.model import GraphSAGEEdgePredictor


class ResidualEdgePredictor(GraphSAGEEdgePredictor):
    """Signed-residual GraphSAGE: identity edge head (no softplus floor)."""

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
        context_attr: torch.Tensor,
        edge_sample_index: torch.Tensor | None = None,
    ) -> torch.Tensor:
        h = self.encode_nodes(x, edge_index)
        if edge_sample_index is None:
            src, dst, edge_inputs = edge_index[0], edge_index[1], edge_attr
        else:
            src = edge_index[0, edge_sample_index]
            dst = edge_index[1, edge_sample_index]
            edge_inputs = edge_attr[edge_sample_index]
        z = torch.cat([h[src], h[dst], edge_inputs, context_attr], dim=-1)
        return self.edge_head(z).squeeze(-1)  # signed — no softplus
