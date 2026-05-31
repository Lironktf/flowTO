from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


try:
    from torch_geometric.nn import SAGEConv

    PYG_AVAILABLE = True
except Exception:  # pragma: no cover - depends on optional install
    SAGEConv = None
    PYG_AVAILABLE = False


class GraphSAGEEdgePredictor(nn.Module):
    """GraphSAGE node encoder plus edge-level congestion-pressure head."""

    def __init__(
        self,
        node_in_dim: int,
        edge_in_dim: int,
        context_in_dim: int,
        hidden_dim: int = 128,
        num_layers: int = 2,
        dropout: float = 0.15,
    ) -> None:
        super().__init__()
        if not PYG_AVAILABLE:
            raise ImportError("torch_geometric is required for GraphSAGEEdgePredictor")
        if num_layers < 1:
            raise ValueError("num_layers must be >= 1")

        self.dropout = dropout
        self.convs = nn.ModuleList()
        self.convs.append(SAGEConv(node_in_dim, hidden_dim))
        for _ in range(num_layers - 1):
            self.convs.append(SAGEConv(hidden_dim, hidden_dim))

        self.edge_head = nn.Sequential(
            nn.Linear(hidden_dim * 2 + edge_in_dim + context_in_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1),
        )

    def encode_nodes(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        h = x
        for conv in self.convs:
            h = conv(h, edge_index)
            h = F.relu(h)
            h = F.dropout(h, p=self.dropout, training=self.training)
        return h

    def score_edges(
        self,
        h: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
        context_attr: torch.Tensor,
        edge_sample_index: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Edge-head pass on precomputed node embeddings ``h``.

        Split out from ``forward`` so callers that score many edge batches over
        the *same* graph encode the nodes once instead of re-running message
        passing per batch (the encoding is independent of which edges are scored).
        """
        if edge_sample_index is None:
            src = edge_index[0]
            dst = edge_index[1]
            edge_inputs = edge_attr
        else:
            src = edge_index[0, edge_sample_index]
            dst = edge_index[1, edge_sample_index]
            edge_inputs = edge_attr[edge_sample_index]
        z = torch.cat([h[src], h[dst], edge_inputs, context_attr], dim=-1)
        return F.softplus(self.edge_head(z).squeeze(-1))

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
        context_attr: torch.Tensor,
        edge_sample_index: torch.Tensor | None = None,
    ) -> torch.Tensor:
        h = self.encode_nodes(x, edge_index)
        return self.score_edges(h, edge_index, edge_attr, context_attr, edge_sample_index)


class GraphFeatureEdgeMLP(nn.Module):
    """Fallback that uses precomputed graph/node/edge features without message passing."""

    def __init__(
        self,
        node_in_dim: int,
        edge_in_dim: int,
        context_in_dim: int,
        hidden_dim: int = 128,
        dropout: float = 0.15,
    ) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(node_in_dim * 2 + edge_in_dim + context_in_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def encode_nodes(self, x: torch.Tensor, edge_index: torch.Tensor | None = None) -> torch.Tensor:
        # No message passing: the "encoding" is just the raw node features. Kept
        # for interface parity with GraphSAGEEdgePredictor so callers can encode
        # once and score many edge batches the same way.
        return x

    def score_edges(
        self,
        h: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
        context_attr: torch.Tensor,
        edge_sample_index: torch.Tensor | None = None,
    ) -> torch.Tensor:
        if edge_sample_index is None:
            src = edge_index[0]
            dst = edge_index[1]
            edge_inputs = edge_attr
        else:
            src = edge_index[0, edge_sample_index]
            dst = edge_index[1, edge_sample_index]
            edge_inputs = edge_attr[edge_sample_index]
        z = torch.cat([h[src], h[dst], edge_inputs, context_attr], dim=-1)
        return F.softplus(self.net(z).squeeze(-1))

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
        context_attr: torch.Tensor,
        edge_sample_index: torch.Tensor | None = None,
    ) -> torch.Tensor:
        h = self.encode_nodes(x, edge_index)
        return self.score_edges(h, edge_index, edge_attr, context_attr, edge_sample_index)


def build_model(
    backend: str,
    node_in_dim: int,
    edge_in_dim: int,
    context_in_dim: int,
    hidden_dim: int = 128,
    num_layers: int = 2,
    dropout: float = 0.15,
) -> nn.Module:
    if backend == "graphsage":
        return GraphSAGEEdgePredictor(
            node_in_dim=node_in_dim,
            edge_in_dim=edge_in_dim,
            context_in_dim=context_in_dim,
            hidden_dim=hidden_dim,
            num_layers=num_layers,
            dropout=dropout,
        )
    if backend == "mlp":
        return GraphFeatureEdgeMLP(
            node_in_dim=node_in_dim,
            edge_in_dim=edge_in_dim,
            context_in_dim=context_in_dim,
            hidden_dim=hidden_dim,
            dropout=dropout,
        )
    raise ValueError(f"unknown backend {backend!r}")

