"""WS /day/stream — a view streams 24 hourly frames for free playback."""

from __future__ import annotations

import json

import networkx as nx
from fastapi.testclient import TestClient

from torontosim.api import create_app
from torontosim.api.daycompute import hour_order
from torontosim.api.encoding import unpack_day_frame_header, unpack_frame
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


def _drain_day_stream(ws, epoch):
    """Collect (hours_in_completion_order, meta) until the 'done' message."""
    hours, meta = [], None
    while True:
        msg = ws.receive()
        if msg.get("text") is not None:
            obj = json.loads(msg["text"])
            if obj.get("type") == "meta":
                meta = obj
            elif obj.get("type") == "done":
                return hours, meta
        elif msg.get("bytes") is not None:
            buf = msg["bytes"]
            hour, ep, off = unpack_day_frame_header(buf)
            assert ep == epoch
            unpack_frame(buf[off:])  # body must decode
            hours.append(hour)


def test_day_stream_emits_all_24_hours():
    client = TestClient(create_app(_small_state()))
    epoch = 7
    with client.websocket_connect("/day/stream") as ws:
        ws.send_json(
            {
                "demand_model": "xgboost",
                "time_context": {"day_of_week": 4, "month": 6},
                "interventions": [],
                "current_hour": 2,
                "epoch": epoch,
                "iterations": 2,
            }
        )
        hours, meta = _drain_day_stream(ws, epoch)

    assert sorted(hours) == list(range(24)), "every hour 0..23 streamed exactly once"
    assert meta and meta["total"] == 24 and meta["epoch"] == epoch
    assert meta["model_actual"]  # non-empty: surfaces the real model / heuristic fallback


def test_day_stream_drops_unknown_edge_ops_without_crashing():
    """A closure on a non-existent edge is filtered out, not fatal to the stream."""
    client = TestClient(create_app(_small_state()))
    with client.websocket_connect("/day/stream") as ws:
        ws.send_json(
            {
                "demand_model": "xgboost",
                "time_context": {"day_of_week": 4, "month": 6},
                "interventions": [{"op": "close_edge", "edge_id": "does-not-exist"}],
                "current_hour": 8,
                "epoch": 1,
                "iterations": 2,
            }
        )
        hours, meta = _drain_day_stream(ws, 1)
    assert sorted(hours) == list(range(24))


def test_hour_order_current_first_then_neighbours():
    assert hour_order(8)[0] == 8
    assert set(hour_order(8)[:5]) == {8, 9, 7, 10, 6}
    assert sorted(hour_order(0)) == list(range(24))  # wraps, covers all
    assert sorted(hour_order(23)) == list(range(24))
