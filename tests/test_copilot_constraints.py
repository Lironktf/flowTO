"""P09 — data-backed constraint checker: real refusals, grounded in graph data."""

from __future__ import annotations

import networkx as nx

from torontosim.api.store import AppState
from torontosim.copilot import constraints
from torontosim.graph import schema


def _state_with_lakeshore():
    """A 4-edge graph with Lake Shore Blvd W in both directions + a residential."""
    g = nx.MultiDiGraph()
    coords = {0: (-79.41, 43.63), 1: (-79.40, 43.63), 2: (-79.40, 43.64), 3: (-79.41, 43.64)}
    for n, (x, y) in coords.items():
        g.add_node(n, x=x, y=y)
    edges = [
        ("ls_eb", 0, 1, "Lake Shore Boulevard West", "primary", True),
        ("ls_wb", 1, 0, "Lake Shore Boulevard West", "primary", True),
        ("king", 2, 3, "King Street West", "secondary", False),
        ("local", 3, 0, "Saulter Street South", "residential", False),
    ]
    for eid, u, v, name, cls, oneway in edges:
        g.add_edge(u, v, key=0, **schema.make_edge(
            edge_id=eid, from_node=u, to_node=v, road_name=name, road_class=cls,
            length_m=500.0, speed_kmh=50.0, lanes=2.0, capacity=1200.0,
            base_time_min=0.6, one_way=oneway,
            geometry=[[coords[u][1], coords[u][0]], [coords[v][1], coords[v][0]]],
        ))
    od = [{"origin": 0, "destination": 3, "trips": 800.0}]
    return AppState.from_graph(g, od, weather="clear", time_context={"hour": 17})


# ---- text-only path (backward compatible with the rehearsed prompt) -------- #

def test_text_full_closure_lakeshore_blocks_with_citations():
    v = constraints.check_request("Just close Lake Shore both ways.")
    refs = [x.ref for x in v]
    assert any("880" in r for r in refs)
    assert any("TTC" in r for r in refs)


def test_text_partial_lakeshore_not_blocked():
    # A single-direction tweak (no full-closure language) is bylaw-valid.
    assert constraints.check_request("Add a contraflow lane on Lake Shore eastbound.") == []


# ---- data-backed path (interventions resolved against the real graph) ------ #

def test_intervention_closing_both_lakeshore_dirs_blocks():
    state = _state_with_lakeshore()
    ivs = [{"op": "close_edge", "edge_id": "ls_eb"}, {"op": "close_edge", "edge_id": "ls_wb"}]
    v = constraints.check_request("close the waterfront road", ivs, state)
    assert any("880" in x.ref for x in v), "fire-route closure must be refused from edge data"


def test_king_st_closure_blocks_transit_priority():
    state = _state_with_lakeshore()
    v = constraints.check_request("remove this segment", [{"op": "remove_edge", "edge_id": "king"}], state)
    assert any("King" in x.ref for x in v)


def test_residential_closure_is_allowed():
    state = _state_with_lakeshore()
    v = constraints.check_request("close this street", [{"op": "close_edge", "edge_id": "local"}], state)
    assert v == []


# ---- advisories (soft warnings, not refusals) ------------------------------ #

def test_major_arterial_closure_is_an_advisory_not_a_block():
    state = _state_with_lakeshore()
    ivs = [{"op": "close_edge", "edge_id": "ls_eb"}]  # one direction only
    assert constraints.check_request("close eastbound", ivs, state) == []  # not a hard block
    warns = constraints.advisories("close eastbound", ivs, state)
    assert any(w.severity == "warn" and "arterial" in w.note for w in warns)
