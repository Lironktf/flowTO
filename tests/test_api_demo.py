"""P12/P07 — /demo/run serves real engine output on the real graph (cached)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app


def _client():
    return TestClient(create_app(_small_state()))


def test_demo_run_returns_records_aligned_to_edges():
    c = _client()
    n_edges = len(c.get("/edges").json()["edges"])
    r = c.get("/demo/run?scenario=baseline")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body and "records" in body
    assert len(body["records"]) == n_edges
    # Each record is [edge_idx, load, speed, pressure, closure].
    assert all(len(rec) == 5 for rec in body["records"])


def test_demo_surge_worse_than_baseline_and_fix_better():
    c = _client()
    base = c.get("/demo/run?scenario=baseline").json()["summary"]["average_pressure"]
    surge = c.get("/demo/run?scenario=wc_surge").json()["summary"]["average_pressure"]
    fix = c.get("/demo/run?scenario=wc_fix").json()["summary"]["average_pressure"]
    assert surge > base
    assert fix < surge


def test_demo_run_unknown_scenario_422():
    assert _client().get("/demo/run?scenario=nope").status_code == 422
