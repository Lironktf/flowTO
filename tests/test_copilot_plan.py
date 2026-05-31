"""P09 — copilot plan(): mocked-model validation, re-ask, guardrails, router."""

from __future__ import annotations

import json

import pytest

from torontosim.copilot import plan_intervention
from torontosim.copilot.plan import PlanError, plan
from torontosim.copilot.tools import ToolCall


class _FakeState:
    edge_index = {"e0": 0, "e1": 1, "e2": 2}


def _model(replies):
    """A model_call that returns queued replies in order."""
    it = iter(replies)

    def call(_system, _prompt, _schema):
        return next(it)

    return call


def test_plan_validates_a_good_tool_call():
    good = ToolCall(
        tool="preview_intervention",
        interventions=[{"op": "close_edge", "edge_id": "e0"}],
    ).model_dump_json()
    call = plan("close e0", _FakeState(), model_call=_model([good]))
    assert call.tool == "preview_intervention"
    # State-changing → must require confirmation (preview-before-apply).
    assert call.requires_user_confirmation is True


def test_plan_reasks_on_unknown_edge_then_succeeds():
    bad = ToolCall(
        tool="preview_intervention", interventions=[{"op": "close_edge", "edge_id": "nope"}]
    ).model_dump_json()
    good = ToolCall(
        tool="preview_intervention", interventions=[{"op": "close_edge", "edge_id": "e1"}]
    ).model_dump_json()
    call = plan("close a street", _FakeState(), model_call=_model([bad, good]))
    assert call.interventions[0].edge_id == "e1"


def test_plan_rejects_persistent_malformed_json():
    with pytest.raises(PlanError):
        plan("x", _FakeState(), model_call=_model(["not json", "{still bad", "{}x"]))


def test_plan_does_not_self_refuse_warn_dont_block():
    # Warn-don't-block: plan() no longer refuses on constraints (assess attaches
    # warnings downstream). A valid proposal comes back as a confirmable preview.
    good = ToolCall(
        tool="preview_intervention", interventions=[{"op": "close_edge", "edge_id": "e0"}]
    ).model_dump_json()
    out = plan("Just close Lake Shore both ways.", _FakeState(), model_call=_model([good]))
    assert out.blocked is False
    assert out.tool == "preview_intervention"
    assert out.requires_user_confirmation is True


def test_router_mitigate_invokes_optimizer():
    # De-hardcoded: "ease congestion" (mitigate) no longer returns a rehearsed
    # script — it routes to the sim-verified optimizer for a real, scored plan.
    out = plan_intervention(
        "Ease congestion on Strachan near BMO Field.",
        _graph_state(),
        classification={"intent": "mitigate"},
    )
    assert out["tool"] == "preview_intervention"
    assert out["intent"] == "mitigate"
    assert "retrieved_policy" in out
    # When it proposes actions, they're cited to the optimizer (not invented bylaws).
    if out["interventions"]:
        assert any("Optimizer" in c["ref"] for c in out["citations"])
        assert out["requires_user_confirmation"] is True


def _lakeshore_state():
    """A 2-segment Lake Shore (fire-route protected corridor) graph state."""
    import networkx as nx

    from torontosim.api.store import AppState
    from torontosim.graph import schema

    g = nx.MultiDiGraph()
    g.add_node(0, x=-79.41, y=43.63)
    g.add_node(1, x=-79.40, y=43.63)
    for eid, u, v in (("ls1", 0, 1), ("ls2", 1, 0)):
        g.add_edge(
            u,
            v,
            key=0,
            **schema.make_edge(
                edge_id=eid,
                from_node=u,
                to_node=v,
                road_name="Lake Shore Boulevard West",
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
    return AppState.from_graph(
        g,
        [{"origin": 0, "destination": 1, "trips": 100.0}],
        weather="clear",
        time_context={"hour": 17},
    )


def test_router_protected_closure_warns_not_blocks():
    # Warn-don't-block: a full closure of a fire-route corridor attaches a DANGER
    # warning but is NOT refused — the plan is still proposed and confirmable.
    out = plan_intervention(
        "close lake shore",
        _lakeshore_state(),
        classification={"intent": "close_road", "road_name": "Lake Shore"},
    )
    assert out["blocked"] is False
    assert out["tool"] == "preview_intervention"
    assert out["requires_user_confirmation"] is True
    assert any(w["severity"] == "danger" for w in out["warnings"])
    assert any("880" in (w["ref"] or "") for w in out["warnings"])


def _graph_state():
    """A 2-edge named graph so candidate-edge resolution can be exercised."""
    import networkx as nx

    from torontosim.api.store import AppState
    from torontosim.graph import schema

    g = nx.MultiDiGraph()
    for n, (x, y) in {0: (-79.41, 43.63), 1: (-79.40, 43.63), 2: (-79.40, 43.64)}.items():
        g.add_node(n, x=x, y=y)
    g.add_edge(
        0,
        1,
        key=0,
        **schema.make_edge(
            edge_id="dufferin",
            from_node=0,
            to_node=1,
            road_name="Dufferin Street",
            road_class="secondary",
            length_m=500.0,
            speed_kmh=50.0,
            lanes=2.0,
            capacity=1200.0,
            base_time_min=0.6,
            one_way=False,
            geometry=[[43.63, -79.41], [43.63, -79.40]],
        ),
    )
    g.add_edge(
        1,
        2,
        key=0,
        **schema.make_edge(
            edge_id="strachan",
            from_node=1,
            to_node=2,
            road_name="Strachan Avenue",
            road_class="tertiary",
            length_m=400.0,
            speed_kmh=40.0,
            lanes=1.0,
            capacity=800.0,
            base_time_min=0.5,
            one_way=False,
            geometry=[[43.63, -79.40], [43.64, -79.40]],
        ),
    )
    return AppState.from_graph(
        g,
        [{"origin": 0, "destination": 2, "trips": 900.0}],
        weather="clear",
        time_context={"hour": 17},
    )


def test_candidate_edges_resolved_by_name():
    from torontosim.copilot.plan import candidate_edges

    ids = [c["edge_id"] for c in candidate_edges(_graph_state(), "close Strachan Avenue near BMO")]
    assert "strachan" in ids
    assert "dufferin" not in ids  # not named in the prompt


def test_assess_attaches_advisory_for_major_arterial():
    # The major-arterial advisory now flows through the SSOT assess pass as a
    # warn-severity warning (was a plan() citation before warn-don't-block).
    from torontosim.copilot.assess import assess

    state = _graph_state()
    for _u, _v, d in state.graph.edges(data=True):
        if d.get("edge_id") == "strachan":
            d["road_class"] = "primary"
    warnings = assess([{"op": "close_edge", "edge_id": "strachan"}], state, with_rag=False)
    assert any("arterial" in (w.detail or "") for w in warnings)


def test_superlative_close_resolves_to_worst_road():
    # "close the worst road" with no history must NOT fail with "no road matching
    # 'worst'" — it resolves deterministically to the most-congested named road.
    state = _graph_state()
    out = plan_intervention(
        "close the worst road",
        state,
        classification={"intent": "close_road", "road_name": "worst"},
    )
    assert out["tool"] == "preview_intervention"
    assert out["interventions"], "expected a concrete closure, not an unresolved error"
    assert "couldn't resolve" not in out["rationale"].lower()


def test_superlative_explain_resolves_to_worst_road():
    # "why is the worst road congested?" resolves to a real road, never a hallucinated
    # one. The surface phrase 'the worst road' must trigger deterministic resolution.
    state = _graph_state()
    out = plan_intervention(
        "why is the worst road so congested?",
        state,
        classification={"intent": "explain", "road_name": "the worst road"},
    )
    assert out["intent"] == "explain"
    assert out["view"] and out["view"]["road_name"] in {"Dufferin Street", "Strachan Avenue"}


def test_focus_resolves_canonical_name_and_edge_ids():
    # "show me Dufferin" → canonical 'Dufferin Street' + its edge_ids (so the camera
    # fits precisely and the segments highlight), not a bare echoed token.
    out = plan_intervention(
        "show me Dufferin",
        _graph_state(),
        classification={"intent": "focus", "road_name": "Dufferin"},
    )
    assert out["view"]["road_name"] == "Dufferin Street"
    assert "dufferin" in out["view"]["edge_ids"]


@pytest.mark.spark
def test_live_nemotron_parses_rehearsed_prompts():
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
    except (urllib.error.URLError, OSError):
        pytest.skip("Ollama not reachable")
    out = plan_intervention(
        "Reduce capacity on a downtown street for construction.", _FakeState(), use_live=True
    )
    assert "tool" in out
    json.dumps(out)  # serializable
