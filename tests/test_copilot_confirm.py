"""P09 — apply loop: /copilot/confirm creates + runs + compares + explains.

Guardrail: planning must NOT mutate the store; only confirm applies.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app


def _client():
    return TestClient(create_app(_small_state()))


def test_confirm_applies_runs_and_explains():
    c = _client()
    before = c.get("/scenarios").json()["scenarios"]
    r = c.post(
        "/copilot/confirm",
        json={
            "name": "copilot close e0",
            "interventions": [{"op": "close_edge", "edge_id": "e0"}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenario_id"]
    assert "summary" in body and body["summary"]
    assert "summary_delta" in body
    assert isinstance(body["explanation"], str)
    # A scenario was actually created (auto-applied).
    after = c.get("/scenarios").json()["scenarios"]
    assert len(after) == len(before) + 1


def test_confirm_rejects_empty_interventions():
    r = _client().post("/copilot/confirm", json={"interventions": []})
    assert r.status_code == 422


def test_confirm_rejects_unknown_edge():
    r = _client().post(
        "/copilot/confirm",
        json={
            "interventions": [{"op": "close_edge", "edge_id": "ghost"}],
        },
    )
    assert r.status_code == 422


def test_plan_does_not_mutate_store():
    c = _client()
    before = len(c.get("/scenarios").json()["scenarios"])
    c.post("/copilot/plan", json={"prompt": "Ease post-match gridlock near BMO Field."})
    after = len(c.get("/scenarios").json()["scenarios"])
    assert after == before, "planning must be read-only (preview-before-apply)"
