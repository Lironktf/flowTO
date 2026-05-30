"""Compact link-based network for the equilibrium engine (P04).

A source-agnostic representation (TNTP fixtures *or* Liron's NetworkX graph) of
nodes 0..n-1 and directed links with free-flow time + capacity + BPR params,
plus a CSR adjacency so the shortest-path inner loop is fast and deterministic.
``float64`` throughout.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Network:
    n_nodes: int
    tail: np.ndarray  # int64[n_links] — link start node
    head: np.ndarray  # int64[n_links] — link end node
    t0: np.ndarray  # float64[n_links] — free-flow time
    cap: np.ndarray  # float64[n_links] — capacity
    alpha: np.ndarray  # float64[n_links]
    beta: np.ndarray  # float64[n_links]
    # CSR over links sorted by tail: indptr[node]..indptr[node+1] index `order`.
    indptr: np.ndarray
    order: np.ndarray  # link indices grouped by tail
    edge_ids: list  # original edge_id per link (for tie-break + result mapping)

    @property
    def n_links(self) -> int:
        return int(self.tail.shape[0])


def build_network(
    n_nodes: int,
    tail,
    head,
    t0,
    cap,
    alpha,
    beta,
    edge_ids=None,
) -> Network:
    """Assemble a ``Network`` (builds the CSR adjacency)."""
    tail = np.asarray(tail, dtype=np.int64)
    head = np.asarray(head, dtype=np.int64)
    t0 = np.asarray(t0, dtype=np.float64)
    cap = np.asarray(cap, dtype=np.float64)
    alpha = np.asarray(alpha, dtype=np.float64)
    beta = np.asarray(beta, dtype=np.float64)
    n_links = tail.shape[0]
    if edge_ids is None:
        edge_ids = list(range(n_links))

    # CSR: stable sort links by tail so iteration order is deterministic.
    order = np.argsort(tail, kind="stable")
    indptr = np.zeros(n_nodes + 1, dtype=np.int64)
    counts = np.bincount(tail, minlength=n_nodes)
    indptr[1:] = np.cumsum(counts)
    return Network(
        n_nodes=n_nodes,
        tail=tail,
        head=head,
        t0=t0,
        cap=cap,
        alpha=alpha,
        beta=beta,
        indptr=indptr,
        order=order.astype(np.int64),
        edge_ids=list(edge_ids),
    )


def bpr_costs(net: Network, flow: np.ndarray) -> np.ndarray:
    """Vectorized BPR link times for the whole network at the given flows.

    Zero-capacity links get ``inf`` (closed -> never chosen).
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(net.cap > 0, flow / net.cap, np.inf)
        cost = net.t0 * (1.0 + net.alpha * np.power(ratio, net.beta))
    cost = np.where(net.cap > 0, cost, np.inf)
    return cost
