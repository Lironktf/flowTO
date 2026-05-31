"""P09 — name→graph resolution (resolve.py) + the intent router (from PR #31)."""

from __future__ import annotations

import networkx as nx

from torontosim.api.store import AppState
from torontosim.copilot import planner, resolve
from torontosim.copilot.classify import ClassifyResult
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
        g.add_edge(
            u,
            v,
            key=0,
            **schema.make_edge(
                edge_id=eid,
                from_node=u,
                to_node=v,
                road_name=name,
                road_class="primary",
                length_m=500.0,
                speed_kmh=50.0,
                lanes=2.0,
                capacity=1500.0,
                base_time_min=0.6,
                one_way=False,
                geometry=[[0, 0], [0, 0]],
            ),
        )
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


# ---- classify-driven dispatch ---------------------------------------------- #


def _cls(**kw):
    return ClassifyResult(**kw)


def test_dispatch_close_road_resolves_all_segments():
    # "close lake shore" (single direction) isn't a hard-block; it resolves.
    call = planner._dispatch(
        "close lake shore", _state(), _cls(intent="close_road", road_name="Lake Shore"), live=False
    )
    assert call.tool == "preview_intervention"
    assert call.requires_user_confirmation is True
    assert {iv.edge_id for iv in call.interventions} == {"ls1", "ls2"}
    assert all(iv.op == "close_edge" for iv in call.interventions)
    # A focus/fit view directive rides along so the map frames the closure.
    assert call.view is not None and call.view.action == "fit"


def test_dispatch_change_capacity_scales_named_road():
    call = planner._dispatch(
        "halve capacity on lake shore",
        _state(),
        _cls(intent="change_capacity", road_name="Lake Shore", multiplier=0.5),
        live=False,
    )
    assert call.tool == "preview_intervention"
    assert {iv.edge_id for iv in call.interventions} == {"ls1", "ls2"}
    assert all(iv.op == "change_capacity" and iv.multiplier == 0.5 for iv in call.interventions)


def test_dispatch_focus_returns_view_no_plan():
    call = planner._dispatch(
        "show me King", _state(), _cls(intent="focus", road_name="King Street West"), live=False
    )
    assert call.tool == "answer"
    assert not call.interventions
    assert call.view is not None and call.view.action == "fit"
    assert call.view.road_name == "King Street West"


def test_dispatch_query_congestion_is_read_only_answer():
    call = planner._dispatch(
        "where is congestion worst", _state(), _cls(intent="query_congestion"), live=False
    )
    assert call.tool == "answer"
    assert call.requires_user_confirmation is False


def test_dispatch_chat_offline_is_generic_answer():
    call = planner._dispatch("hello there", _state(), _cls(intent="chat"), live=False)
    assert call.tool == "answer"
    assert call.requires_user_confirmation is False


def test_answer_congestion_survives_tied_pressure_and_unnamed_edges():
    # Regression: sorting (pressure, road_name) crashed on the real graph when
    # pressures tied and a road_name was None (str < None unorderable).
    g = nx.MultiDiGraph()
    g.add_edge(0, 1, key=0, road_name=None, status="open", pressure=0.5, load=10)
    g.add_edge(1, 2, key=0, road_name="King Street West", status="open", pressure=0.5, load=10)

    class _FakeState:
        def baseline(self):
            return {"graph": g}

    out = planner._answer_congestion(_FakeState())  # must not raise
    assert isinstance(out, str) and "Congestion is worst" in out


def test_suggested_prompts_are_grounded_in_real_road_names():
    chips = planner.suggested_prompts(_state())
    assert "Where is congestion worst right now?" in chips
    # Chips reference actual arterials from the graph, not hardcoded road names.
    assert any("Lake Shore Boulevard West" in c for c in chips)
    assert all(isinstance(c, str) and c for c in chips)


def test_worst_road_view_fits_most_congested_named_road():
    # A congestion query should fly the camera to the single worst corridor.
    g = nx.MultiDiGraph()
    g.add_edge(
        0,
        1,
        key=0,
        road_name="King Street West",
        edge_id="k1",
        status="open",
        pressure=0.9,
        load=50,
    )
    g.add_edge(
        1,
        2,
        key=0,
        road_name="Queen Street West",
        edge_id="q1",
        status="open",
        pressure=0.4,
        load=50,
    )

    class _S:
        def baseline(self):
            return {"graph": g}

    view = planner._worst_road_view(_S())
    assert view is not None and view.action == "fit"
    assert view.road_name == "King Street West"
    assert view.edge_ids == ["k1"]


def test_dispatch_unresolvable_road_answers_not_found():
    call = planner._dispatch(
        "close the moon",
        _state(),
        _cls(intent="close_road", road_name="Moon Base Alpha"),
        live=False,
    )
    assert call.tool == "answer"
    assert "couldn't resolve" in call.rationale
