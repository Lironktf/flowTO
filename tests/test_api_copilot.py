"""P09 — copilot endpoints wired into the API (no longer 501)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app


def _client():
    return TestClient(create_app(_small_state()))


def test_copilot_plan_mitigate_invokes_optimizer():
    # De-hardcoded: mitigate routes to the sim-verified optimizer (no rehearsed
    # hero script / invented bylaw citations).
    r = _client().post(
        "/copilot/plan",
        json={
            "prompt": "Ease congestion across downtown.",
            "classification": {"intent": "mitigate"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "preview_intervention"
    if body["interventions"]:
        assert any("Optimizer" in c["ref"] for c in body["citations"])
        assert body["requires_user_confirmation"] is True


def test_copilot_plan_warns_not_blocks():
    # Warn-don't-block: /copilot/plan never refuses (no block flag).
    r = _client().post("/copilot/plan", json={"prompt": "Just close Lake Shore both ways."})
    assert r.status_code == 200
    assert r.json()["blocked"] is False


def test_assess_endpoint_returns_severity_coded_warnings():
    # The SSOT assess endpoint returns warnings (never a refusal) for a closure
    # that matches a protected corridor by text.
    r = _client().post(
        "/assess",
        json={"interventions": [{"op": "close_edge", "edge_id": "e0"}],
              "prompt": "close lake shore both ways"},
    )
    assert r.status_code == 200
    ws = r.json()["warnings"]
    assert any(w["severity"] == "danger" for w in ws)


def test_copilot_route_classifies_and_dispatches_inline():
    # /route is the single classifier entry. Offline (no model) it degrades to a
    # chat-mode decision and must never 500. A pre-classified plan intent dispatches
    # inline so the frontend skips a second hop.
    r = _client().post("/copilot/route", json={"prompt": "hello there"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("chat", "plan", "agent")
    assert "intent" in body


def test_copilot_explain_summarizes_deltas():
    r = _client().post(
        "/copilot/explain",
        json={"summary_delta": {"average_pressure": -0.12, "high_risk_edges": -3}},
    )
    assert r.status_code == 200
    assert "eased" in r.json()["explanation"]


def test_optimize_endpoint_returns_ranked_plan():
    r = _client().post("/optimize", json={"objective": "average_pressure", "max_actions": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["solver"] == "heuristic"
    assert body["best_metric"] <= body["baseline_metric"] + 1e-9
    assert "plan" in body


def test_copilot_optimize_intent_invokes_optimizer():
    # "optimize" routes through the copilot to the P10 optimizer and returns a
    # confirmable preview (or a no-improvement note) — never a raw error.
    r = _client().post(
        "/copilot/plan",
        json={
            "prompt": "Optimize the network to cut congestion.",
            "classification": {"intent": "optimize"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "preview_intervention"
    # Either it proposed sim-verified actions (cite the optimizer) or found none.
    if body["interventions"]:
        assert any("Optimizer" in c["ref"] for c in body["citations"])
        assert body["requires_user_confirmation"] is True
