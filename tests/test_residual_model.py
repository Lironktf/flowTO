"""P13 §C — residual model tests (torch/PyG; runs on the GB10)."""

from __future__ import annotations

import torch

from torontosim.feedback.model import ResidualEdgePredictor


def _tiny():
    # 3-node ring, 3 edges
    edge_index = torch.tensor([[0, 1, 2], [1, 2, 0]], dtype=torch.long)
    x = torch.randn(3, 4)
    edge_attr = torch.randn(3, 3)
    context = torch.randn(3, 2)
    return x, edge_index, edge_attr, context


def test_forward_shape():
    torch.manual_seed(0)
    m = ResidualEdgePredictor(node_in_dim=4, edge_in_dim=3, context_in_dim=2, hidden_dim=8)
    x, ei, ea, ctx = _tiny()
    out = m(x, ei, ea, ctx)
    assert out.shape == (3,)


def test_signed_head_can_predict_negative():
    """The identity head (no softplus) must be able to reach negative residuals."""
    torch.manual_seed(0)
    m = ResidualEdgePredictor(node_in_dim=4, edge_in_dim=3, context_in_dim=2, hidden_dim=8)
    x, ei, ea, ctx = _tiny()
    target = torch.full((3,), -5.0)
    opt = torch.optim.Adam(m.parameters(), lr=0.05)
    loss_fn = torch.nn.SmoothL1Loss()
    first = None
    for _ in range(300):
        opt.zero_grad()
        pred = m(x, ei, ea, ctx)
        loss = loss_fn(pred, target)
        if first is None:
            first = float(loss)
        loss.backward()
        opt.step()
    assert float(loss) < first              # learned
    assert float(m(x, ei, ea, ctx).mean()) < 0  # reached negative (softplus could not)
