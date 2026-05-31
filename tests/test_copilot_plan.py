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


def test_plan_refuses_hard_constraint_breach():
    # Even if the model proposes it, the constraint check refuses.
    call = ToolCall(tool="preview_intervention").model_dump_json()
    out = plan("Just close Lake Shore both ways.", _FakeState(), model_call=_model([call]))
    assert out.blocked is True
    assert any("880" in c.ref for c in out.citations)


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


def test_router_blocked_request_refuses_unchanged():
    out = plan_intervention("Just close Lake Shore both ways.", _FakeState())
    assert out["blocked"] is True
    assert out["requires_user_confirmation"] is False
    refs = [c["ref"] for c in out["citations"]]
    assert any("880" in r for r in refs)


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


def test_plan_attaches_advisory_for_major_arterial(monkeypatch):
    state = _graph_state()
    # Promote Strachan to a major arterial so the advisory fires.
    for _u, _v, d in state.graph.edges(data=True):
        if d.get("edge_id") == "strachan":
            d["road_class"] = "primary"
    good = ToolCall(
        tool="preview_intervention", interventions=[{"op": "close_edge", "edge_id": "strachan"}]
    ).model_dump_json()
    call = plan("close Strachan", state, model_call=_model([good]))
    assert any("arterial" in c.note for c in call.citations)


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
