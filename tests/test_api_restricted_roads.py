"""Restricted-road closure guardrail: TCL-derived classification + /edges flag."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app
from torontosim.api.restricted_roads import classify_edge, restricted_index


def _write_artifact(data_dir, edges: dict) -> None:
    graph_dir = data_dir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "restricted_roads.json").write_text(
        json.dumps({"count": len(edges), "edges": edges})
    )


def test_classify_edge_labels_each_category(tmp_path):
    _write_artifact(
        tmp_path,
        {
            "e0": {"category": "mto_prohibited", "label": "Highway 401"},
            "e1": {"category": "municipal_expressway", "label": "Gardiner Expressway"},
        },
    )
    mto = classify_edge("e0", str(tmp_path))
    assert mto["category"] == "mto_prohibited"
    assert mto["label"] == "Highway 401"
    assert "MTO" in mto["reason"]

    municipal = classify_edge("e1", str(tmp_path))
    assert municipal["category"] == "municipal_expressway"
    assert "City of Toronto" in municipal["reason"]

    assert classify_edge("e2", str(tmp_path)) is None


def test_missing_artifact_is_graceful(tmp_path):
    assert restricted_index(str(tmp_path)) == {}
    assert classify_edge("e0", str(tmp_path)) is None


def test_edges_endpoint_flags_restricted_edges(tmp_path, monkeypatch):
    _write_artifact(tmp_path, {"e0": {"category": "mto_prohibited", "label": "Highway 401"}})
    monkeypatch.setenv("TS_DATA_DIR", str(tmp_path))

    client = TestClient(create_app(_small_state()))
    edges = client.get("/edges").json()["edges"]
    by_id = {e["edge_id"]: e for e in edges}

    assert by_id["e0"]["restricted"]["category"] == "mto_prohibited"
    assert by_id["e0"]["restricted"]["label"] == "Highway 401"
    assert "restricted" not in by_id["e1"]
