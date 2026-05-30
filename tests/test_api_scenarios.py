"""P06 — REST API: scenario CRUD + run + compare + preview (TestClient)."""

from __future__ import annotations

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from torontosim.api import create_app
from torontosim.api.store import AppState
from torontosim.graph import schema


def _small_state():
    g = nx.MultiDiGraph()
    coords = {0: (-79.40, 43.64), 1: (-79.39, 43.65), 2: (-79.39, 43.63), 3: (-79.38, 43.64)}
    for n, (x, y) in coords.items():
        g.add_node(n, x=x, y=y)
    for i, (u, v) in enumerate([(0, 1), (0, 2), (1, 3), (2, 3)]):
        g.add_edge(
            u,
            v,
            key=0,
            **schema.make_edge(
                edge_id=f"e{i}",
                from_node=u,
                to_node=v,
                road_class="primary",
                length_m=1000.0,
                speed_kmh=50.0,
                lanes=2.0,
                capacity=1200.0,
                base_time_min=1.2,
                one_way=True,
                geometry=[[coords[u][1], coords[u][0]], [coords[v][1], coords[v][0]]],
            ),
        )
    od = [{"origin": 0, "destination": 3, "trips": 1500.0}]
    return AppState.from_graph(g, od, weather="clear", time_context={"hour": 17})


@pytest.fixture
def client():
    return TestClient(create_app(_small_state()))


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["edges"] == 4


def test_create_run_compare_flow(client):
    # Create with a closure intervention.
    r = client.post(
        "/scenarios",
        json={
            "name": "close e0",
            "interventions": [{"op": "close_edge", "edge_id": "e0"}],
        },
    )
    assert r.status_code == 200
    sid = r.json()["id"]

    # Run it.
    rr = client.post(f"/scenarios/{sid}/run", json={"recompute": "full"})
    assert rr.status_code == 200
    assert "summary" in rr.json()

    # Compare against baseline → deltas present.
    rc = client.get(f"/scenarios/{sid}/compare?against=baseline")
    assert rc.status_code == 200
    body = rc.json()
    assert body["scenario_id"] == sid
    assert "summary_delta" in body


def test_preview_does_not_mutate_state(client):
    r = client.post(
        "/scenarios", json={"name": "p", "interventions": [{"op": "close_edge", "edge_id": "e1"}]}
    )
    sid = r.json()["id"]
    n_before = len(client.get("/scenarios").json()["scenarios"])
    rp = client.post(f"/scenarios/{sid}/preview", json={})
    assert rp.status_code == 200
    assert rp.json()["mutated"] is False
    n_after = len(client.get("/scenarios").json()["scenarios"])
    assert n_before == n_after


def test_bad_edge_id_returns_422(client):
    r = client.post(
        "/scenarios",
        json={"name": "bad", "interventions": [{"op": "close_edge", "edge_id": "nope"}]},
    )
    sid = r.json()["id"]
    rr = client.post(f"/scenarios/{sid}/run", json={})
    assert rr.status_code == 422


def test_run_is_deterministic(client):
    r = client.post(
        "/scenarios", json={"name": "d", "interventions": [{"op": "close_edge", "edge_id": "e0"}]}
    )
    sid = r.json()["id"]
    a = client.post(f"/scenarios/{sid}/run", json={"recompute": "full"}).json()
    b = client.post(f"/scenarios/{sid}/run", json={"recompute": "full"}).json()
    assert a["summary"] == b["summary"]


def test_blast_run_reports_stats(client):
    r = client.post(
        "/scenarios",
        json={"name": "blast", "interventions": [{"op": "close_edge", "edge_id": "e0"}]},
    )
    sid = r.json()["id"]
    rr = client.post(f"/scenarios/{sid}/run", json={"recompute": "blast"}).json()
    assert rr["recompute"] == "blast"
    assert rr["blast_stats"] is not None
