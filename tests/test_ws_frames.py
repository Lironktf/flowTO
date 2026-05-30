"""P06 — WebSocket binary tick frames decode to the expected record layout."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app
from torontosim.api.encoding import RECORD_SIZE, pack_frame, unpack_frame


def test_encoding_roundtrip():
    records = [(0, 100.5, 42.0, 0.8, False), (1, 0.0, 0.0, 0.0, True)]
    buf = pack_frame(records)
    out = unpack_frame(buf)
    assert len(out) == 2
    assert out[0][0] == 0
    assert abs(out[0][1] - 100.5) < 1e-3
    assert out[1][4] == 1  # closure flag
    assert len(buf) == 4 + 2 * RECORD_SIZE


def test_ws_streams_decodable_frames():
    client = TestClient(create_app(_small_state()))
    r = client.post(
        "/scenarios", json={"name": "ws", "interventions": [{"op": "close_edge", "edge_id": "e0"}]}
    )
    sid = r.json()["id"]
    with client.websocket_connect(f"/scenarios/{sid}/stream") as ws:
        data = ws.receive_bytes()
    records = unpack_frame(data)
    assert len(records) >= 1
    # Each record is a 5-tuple (idx, load, speed, pressure, closure).
    assert all(len(rec) == 5 for rec in records)
    # The closed edge e0 reports closure=1.
    state = _small_state()
    e0_idx = state.edge_index["e0"]
    closed = [rec for rec in records if rec[0] == e0_idx]
    assert closed and closed[0][4] == 1
