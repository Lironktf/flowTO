"""P09 — /copilot/stream SSE: token stream + latency HUD (mocked model)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app
from torontosim.copilot import ollama_client


def _events(monkeypatch):
    """Make ollama_client.stream yield two tokens then a done event."""
    def fake_stream(_system, _prompt, _schema=None, *, timeout=180.0):
        yield {"token": "Egress ", "done": False, "first": True, "total_ms": None}
        yield {"token": "improves.", "done": False, "first": False, "total_ms": None}
        yield {"token": "", "done": True, "first": False, "total_ms": 1234}

    monkeypatch.setattr(ollama_client, "stream", fake_stream)


def test_stream_emits_tokens_then_latency(monkeypatch):
    _events(monkeypatch)
    c = TestClient(create_app(_small_state()))
    with c.stream("POST", "/copilot/stream", json={"prompt": "why did egress improve?"}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        payloads = [
            json.loads(line[len("data: "):])
            for line in r.iter_lines()
            if line.startswith("data: ")
        ]
    tokens = "".join(p.get("token", "") for p in payloads)
    assert "Egress" in tokens
    done = payloads[-1]
    assert done["done"] is True
    assert done["total_ms"] == 1234
    assert done["first_token_ms"] is not None  # HUD: first-token latency captured


def test_stream_surfaces_errors_as_done(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("model unreachable")
        yield  # pragma: no cover — generator

    monkeypatch.setattr(ollama_client, "stream", boom)
    c = TestClient(create_app(_small_state()))
    with c.stream("POST", "/copilot/stream", json={"prompt": "x"}) as r:
        payloads = [
            json.loads(line[len("data: "):])
            for line in r.iter_lines()
            if line.startswith("data: ")
        ]
    assert payloads[-1]["done"] is True
    assert "error" in payloads[-1]
