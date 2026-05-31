"""Follow-up prompt suggestions: pure function + /copilot/followups endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app
from torontosim.copilot.followups import followups

_INTENTS = [
    "close_road",
    "close_segment",
    "reopen_road",
    "reopen_segment",
    "change_capacity",
    "query_congestion",
    "explain",
    "inspect",
    "optimize",
    "mitigate",
    "investigate",
    "focus",
    "set_time",
    "chat",
    "",  # unknown -> default
]


def _client():
    return TestClient(create_app(_small_state()))


@pytest.mark.parametrize("intent", _INTENTS)
def test_followups_returns_nonempty_string_list(intent):
    out = followups("Close King St", "Done.", intent)
    assert isinstance(out, list)
    assert 2 <= len(out) <= 4
    assert all(isinstance(p, str) and p for p in out)


@pytest.mark.parametrize("intent", _INTENTS)
def test_followups_endpoint_returns_prompts(intent):
    r = _client().post(
        "/copilot/followups",
        json={"prompt": "Close King St", "reply": "Done.", "intent": intent},
    )
    assert r.status_code == 200
    prompts = r.json()["prompts"]
    assert isinstance(prompts, list)
    assert 2 <= len(prompts) <= 4
    assert all(isinstance(p, str) and p for p in prompts)
