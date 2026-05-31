"""P09 — single intent classifier: mocked-model parsing, mode derivation, fallback."""

from __future__ import annotations

import json

from torontosim.copilot.classify import ClassifyResult, classify


def _model(payload: dict):
    return lambda _s, _p, _sc: json.dumps(payload)


def test_classify_passes_history_for_reference_resolution():
    # 'the worst road' must be resolvable from recent conversation — the history
    # is fed into the model prompt so it can extract the concrete road name.
    seen = {}

    def cap(_system, prompt, _schema):
        seen["prompt"] = prompt
        return json.dumps({"intent": "explain", "road_name": "Browning Avenue"})

    res = classify(
        "why is the worst road congested?",
        history="Copilot: Congestion is worst on Browning Avenue (v/c 16.9).",
        model_call=cap,
    )
    assert "Browning Avenue" in seen["prompt"]  # history reached the model
    assert res.road_name == "Browning Avenue"


def test_mode_derivation_from_intent():
    assert ClassifyResult(intent="close_road").mode == "plan"
    assert ClassifyResult(intent="query_congestion").mode == "plan"
    assert ClassifyResult(intent="focus").mode == "plan"
    assert ClassifyResult(intent="investigate").mode == "agent"
    assert ClassifyResult(intent="chat").mode == "chat"


def test_classify_parses_close_road_with_name():
    res = classify(
        "can you close King Street?",
        model_call=_model({"intent": "close_road", "road_name": "King Street"}),
    )
    assert res.intent == "close_road"
    assert res.road_name == "King Street"
    assert res.mode == "plan"


def test_classify_parses_segment_intersections():
    res = classify(
        "close King between Bathurst and Spadina",
        model_call=_model(
            {
                "intent": "close_segment",
                "from_intersection": "King & Bathurst",
                "to_intersection": "King & Spadina",
            }
        ),
    )
    assert res.intent == "close_segment"
    assert res.from_intersection == "King & Bathurst"
    assert res.to_intersection == "King & Spadina"


def test_classify_falls_back_to_chat_on_bad_model_output():
    # Garbage / unreachable model must degrade to a safe conversational reply,
    # never raise — routing stays alive.
    def _broken(_s, _p, _sc):
        return "not json at all"

    assert classify("hello", model_call=_broken).intent == "chat"


def test_classify_falls_back_to_chat_on_model_error():
    def _raises(_s, _p, _sc):
        raise OSError("model unreachable")

    assert classify("anything", model_call=_raises).mode == "chat"
