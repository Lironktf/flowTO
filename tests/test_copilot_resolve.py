"""P09 — name→graph resolution (resolve.py) + the intent router (from PR #31)."""

from __future__ import annotations

import json

import networkx as nx

from torontosim.api.store import AppState
from torontosim.copilot import planner, resolve
from torontosim.graph import schema


def _state():
    """A small named graph: Lake Shore W (2 segments) + King St, with intersections."""
    g = nx.MultiDiGraph()
    g.add_node(0, x=-79.41, y=43.63, name="Lake Shore Boulevard West & Strachan Avenue")
    g.add_node(1, x=-79.40, y=43.63, name="Lake Shore Boulevard West & Bathurst Street")
    g.add_node(2, x=-79.40, y=43.64, name="King Street West & Bathurst Street")
    edges = [
        ("ls1", 0, 1, "Lake Shore Boulevard West"),
        ("ls2", 1, 0, "Lake Shore Boulevard West"),
        ("king1", 1, 2, "King Street West"),
    ]
    for eid, u, v, name in edges:
        g.add_edge(u, v, key=0, **schema.make_edge(
            edge_id=eid, from_node=u, to_node=v, road_name=name, road_class="primary",
            length_m=500.0, speed_kmh=50.0, lanes=2.0, capacity=1500.0, base_time_min=0.6,
            one_way=False, geometry=[[0, 0], [0, 0]]))
    od = [{"origin": 0, "destination": 2, "trips": 600.0}]
    return AppState.from_graph(g, od, weather="clear", time_context={"hour": 17})


# ---- resolve.py ------------------------------------------------------------ #

def test_road_edges_by_name_fuzzy_matches_whole_road():
    g = _state().graph
    res = resolve.road_edges_by_name(g, "lake shore")  # partial, lowercase
    assert res["found"] is True
    assert res["road_name"] == "Lake Shore Boulevard West"
    assert set(res["edge_ids"]) == {"ls1", "ls2"}


def test_road_edges_by_name_unknown_returns_not_found():
    res = resolve.road_edges_by_name(_state().graph, "nonexistent parkway")
    assert res["found"] is False
    assert "reason" in res


def test_resolve_node_by_name_handles_ampersand_variants():
    g = _state().graph
    for q in ("Lake Shore & Bathurst", "lake shore boulevard west and bathurst"):
        hit = resolve.resolve_node_by_name(g, q)
        assert hit is not None and hit[0] == 1


# ---- intent router --------------------------------------------------------- #

def _model(payload: dict):
    return lambda _s, _p, _sc: json.dumps(payload)


def test_router_close_road_resolves_all_segments():
    call = planner._try_command("close lake shore", _state(),
                                _model({"intent": "close_road", "road_name": "Lake Shore"}))
    assert call.tool == "preview_intervention"
    assert call.requires_user_confirmation is True
    assert {iv.edge_id for iv in call.interventions} == {"ls1", "ls2"}
    assert all(iv.op == "close_edge" for iv in call.interventions)


def test_router_query_congestion_is_read_only_answer():
    call = planner._try_command("where is congestion worst", _state(),
                                _model({"intent": "query_congestion"}))
    assert call.tool == "answer"
    assert call.requires_user_confirmation is False


def test_router_other_falls_through():
    call = planner._try_command("reduce capacity on King", _state(), _model({"intent": "other"}))
    assert call is None


def test_router_unresolvable_road_answers_not_found():
    call = planner._try_command("close the moon", _state(),
                                _model({"intent": "close_road", "road_name": "Moon Base Alpha"}))
    assert call.tool == "answer"
    assert "couldn't resolve" in call.rationale
