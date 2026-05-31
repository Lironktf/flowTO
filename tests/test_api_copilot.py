"""P09 — copilot endpoints wired into the API (no longer 501)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app


def _client():
    return TestClient(create_app(_small_state()))


def test_copilot_plan_hero_returns_cited_preview():
    r = _client().post(
        "/copilot/plan",
        json={"prompt": "Ease post-match gridlock near BMO Field without breaking bylaws."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "preview_intervention"
    assert body["requires_user_confirmation"] is True
    assert any("950" in c["ref"] for c in body["citations"])


def test_copilot_plan_blocked_refuses():
    r = _client().post("/copilot/plan", json={"prompt": "Just close Lake Shore both ways."})
    assert r.status_code == 200
    body = r.json()
    assert body["blocked"] is True
    assert any("880" in c["ref"] for c in body["citations"])


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
    r = _client().post("/copilot/plan", json={"prompt": "Optimize the network to cut congestion."})
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "preview_intervention"
    # Either it proposed sim-verified actions (cite the optimizer) or found none.
    if body["interventions"]:
        assert any("Optimizer" in c["ref"] for c in body["citations"])
        assert body["requires_user_confirmation"] is True
