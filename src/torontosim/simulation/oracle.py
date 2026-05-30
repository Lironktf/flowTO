"""TNTP fixtures + AequilibraE oracle harness for the UE engine (P04, test-side).

Parses the standard TNTP format (Transportation Networks repo) for a network,
its OD trip table, and its **published equilibrium link flows** — the canonical
offline correctness anchor. Optionally runs AequilibraE ``bfw`` for a second
opinion. Used by ``tests/test_equilibrium_oracle.py``.
"""

from __future__ import annotations

import re

import numpy as np

from .network import build_network


def _data_lines(text: str):
    """Yield post-metadata, non-comment rows of a TNTP file."""
    started = False
    for line in text.splitlines():
        if "<END OF METADATA>" in line:
            started = True
            continue
        if not started:
            continue
        s = line.strip()
        if not s or s.startswith("~"):
            continue
        yield s


def parse_tntp_net(text: str):
    """Return (n_nodes, links) where links are dicts with BPR fields (0-indexed)."""
    n_nodes = 0
    m = re.search(r"<NUMBER OF NODES>\s+(\d+)", text)
    if m:
        n_nodes = int(m.group(1))
    links = []
    for s in _data_lines(text):
        parts = s.rstrip(";").split()
        if len(parts) < 7:
            continue
        init, term, cap, length, fft, b, power = parts[:7]
        links.append(
            {
                "tail": int(init) - 1,
                "head": int(term) - 1,
                "cap": float(cap),
                "length": float(length),
                "fft": float(fft),
                "alpha": float(b),
                "beta": float(power),
            }
        )
    n_nodes = max(n_nodes, 1 + max(max(li["tail"], li["head"]) for li in links))
    return n_nodes, links


def parse_tntp_trips(text: str):
    """Return OD list ``[(origin, dest, demand), ...]`` (0-indexed nodes)."""
    od = []
    origin = None
    for line in text.splitlines():
        s = line.strip()
        if s.lower().startswith("origin"):
            origin = int(s.split()[1]) - 1
            continue
        if origin is None or ":" not in s:
            continue
        for chunk in s.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            dest_s, flow_s = chunk.split(":")
            demand = float(flow_s)
            if demand > 0:
                od.append((origin, int(dest_s) - 1, demand))
    return od


def parse_tntp_flow(text: str):
    """Return published equilibrium flows ``{(tail, head): volume}`` (0-indexed)."""
    flows = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            tail = int(parts[0]) - 1
            head = int(parts[1]) - 1
            vol = float(parts[2])
        except ValueError:
            continue  # header row
        flows[(tail, head)] = vol
    return flows


def build_network_from_tntp(net_text: str):
    """Build a ``Network`` from TNTP net text (edge_ids = (tail, head) tuples)."""
    n_nodes, links = parse_tntp_net(net_text)
    tail = [li["tail"] for li in links]
    head = [li["head"] for li in links]
    fft = [li["fft"] for li in links]
    cap = [li["cap"] for li in links]
    alpha = [li["alpha"] for li in links]
    beta = [li["beta"] for li in links]
    edge_ids = [(li["tail"], li["head"]) for li in links]
    net = build_network(n_nodes, tail, head, fft, cap, alpha, beta, edge_ids=edge_ids)
    return net


def published_flow_vector(net, flows: dict) -> np.ndarray:
    """Align a published ``{(tail,head): vol}`` map to the network's link order."""
    return np.array([flows.get(eid, np.nan) for eid in net.edge_ids], dtype=np.float64)
