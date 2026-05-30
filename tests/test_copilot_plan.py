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


def test_router_hero_returns_cited_preview():
    out = plan_intervention(
        "Ease post-match gridlock near BMO Field without breaking bylaws.", _FakeState()
    )
    assert out["tool"] == "preview_intervention"
    assert out["requires_user_confirmation"] is True
    refs = [c["ref"] for c in out["citations"]]
    assert any("950" in r for r in refs)
    assert "retrieved_policy" in out


def test_router_blocked_request_refuses_unchanged():
    out = plan_intervention("Just close Lake Shore both ways.", _FakeState())
    assert out["blocked"] is True
    assert out["requires_user_confirmation"] is False
    refs = [c["ref"] for c in out["citations"]]
    assert any("880" in r for r in refs)


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
