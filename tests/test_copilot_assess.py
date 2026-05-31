"""P09 — SSOT assess(): warn-don't-block, severity floor, never refuses."""

from __future__ import annotations

import networkx as nx

from torontosim.copilot.assess import assess


class _S:
    def __init__(self, g):
        self.graph = g


def _g(road_name: str, road_class: str, eid: str = "x"):
    g = nx.MultiDiGraph()
    g.add_edge(
        0, 1, key=0, edge_id=eid, road_name=road_name, road_class=road_class, from_node=0, to_node=1
    )
    return g


def test_assess_protected_full_closure_is_danger_not_block():
    ws = assess(
        [{"op": "close_edge", "edge_id": "x"}],
        _S(_g("Quiet Lane", "residential")),
        prompt="close lake shore both ways",
        with_rag=False,
    )
    assert any(w.severity == "danger" for w in ws)
    assert any("880" in (w.ref or "") for w in ws)  # fire-route bylaw cited


def test_assess_major_arterial_is_warn():
    ws = assess(
        [{"op": "close_edge", "edge_id": "x"}], _S(_g("Generic Rd", "primary")), with_rag=False
    )
    assert any(w.severity == "warn" for w in ws)
    assert all(w.severity != "danger" for w in ws)


def test_assess_benign_closure_has_no_danger():
    ws = assess(
        [{"op": "close_edge", "edge_id": "x"}], _S(_g("Quiet Lane", "residential")), with_rag=False
    )
    assert all(w.severity != "danger" for w in ws)


def test_assess_returns_warnings_never_a_refusal():
    # The worst case is still just a (override-able) warning list — no block flag.
    ws = assess(
        [{"op": "close_edge", "edge_id": "x"}],
        _S(_g("Quiet Lane", "residential")),
        prompt="close lake shore both ways",
        with_rag=False,
    )
    assert isinstance(ws, list)
    assert all(w.severity in ("info", "warn", "danger") for w in ws)


def test_assess_dedupes_identical_warnings():
    ws = assess(
        [{"op": "close_edge", "edge_id": "x"}, {"op": "close_edge", "edge_id": "x"}],
        _S(_g("Generic Rd", "primary")),
        with_rag=False,
    )
    keys = [(w.severity, w.ref, w.detail) for w in ws]
    assert len(keys) == len(set(keys))
