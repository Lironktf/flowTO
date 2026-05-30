"""P09 — bounded read-only multi-tool agent loop (mocked model)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app
from torontosim.copilot.agent import AgentStep, run_agent


def _script(*steps: dict):
    """A model_call yielding the queued AgentStep dicts as JSON."""
    q = [AgentStep(**s).model_dump_json() for s in steps]

    def call(_system, _prompt, _schema):
        return q.pop(0)

    return call


def test_agent_investigates_then_proposes():
    state = _small_state()
    model = _script(
        {"tool": "retrieve_policy", "query": "event traffic management"},
        {"tool": "simulate", "interventions": [{"op": "change_capacity", "edge_id": "e0", "multiplier": 0.5}]},
        {"tool": "propose",
         "interventions": [{"op": "change_capacity", "edge_id": "e0", "multiplier": 0.5}],
         "rationale": "Metering e0 eases the spine."},
    )
    res = run_agent("ease congestion and check it helps", state, model_call=model)
    assert res.requires_user_confirmation is True
    assert res.interventions[0].edge_id == "e0"
    # It investigated (retrieve + simulate) before proposing; the trace now
    # records the terminal step too.
    assert [s["tool"] for s in res.steps] == ["retrieve_policy", "simulate", "propose"]


def test_agent_refuses_blocked_proposal():
    state = _small_state()
    model = _script(
        {"tool": "propose", "interventions": [{"op": "close_edge", "edge_id": "e0"}],
         "rationale": "close it"},
    )
    res = run_agent("Just close Lake Shore both ways.", state, model_call=model)
    assert res.blocked is True
    assert res.requires_user_confirmation is False


def test_agent_answer_terminates_without_plan():
    state = _small_state()
    model = _script({"tool": "answer", "answer": "Egress peaks 17:00–18:30."})
    res = run_agent("when does egress peak?", state, model_call=model)
    assert res.interventions == []
    assert "Egress" in res.answer


def test_agent_step_cap_terminates():
    state = _small_state()
    # Always simulate, never terminate → must stop at the cap.
    def model(_s, _p, _sch):
        return AgentStep(tool="simulate", interventions=[]).model_dump_json()

    res = run_agent("loop forever", state, model_call=model, max_steps=3)
    assert len(res.steps) == 3
    assert res.interventions == []


def test_agent_simulate_skips_malformed_intervention():
    # Regression: the model sometimes emits an edge op with no edge_id; it must
    # be dropped, not crash the sim (KeyError: 'edge_id').
    state = _small_state()
    model = _script(
        {"tool": "simulate", "interventions": [{"op": "change_capacity", "multiplier": 0.5}]},
        {"tool": "answer", "answer": "done"},
    )
    res = run_agent("x", state, model_call=model)  # must not raise
    assert res.steps[0]["observation"].get("error")


def test_agent_endpoint_is_read_only_when_model_unreachable():
    # No live model in CI → loop breaks to a forced summary; store untouched, 200.
    c = TestClient(create_app(_small_state()))
    before = len(c.get("/scenarios").json()["scenarios"])
    r = c.post("/copilot/agent", json={"prompt": "investigate congestion near BMO"})
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    json.dumps(body)  # serializable
    after = len(c.get("/scenarios").json()["scenarios"])
    assert after == before
