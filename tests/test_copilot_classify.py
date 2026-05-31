"""P09 — single intent classifier: mocked-model parsing, mode derivation, fallback."""

from __future__ import annotations

import json

from torontosim.copilot.classify import ClassifyResult, classify


def _model(payload: dict):
    return lambda _s, _p, _sc: json.dumps(payload)


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
