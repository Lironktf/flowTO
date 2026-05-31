"""Context-aware follow-up prompt suggestions for the copilot.

After each copilot reply the frontend shows a few "next question" chips. This
is a deterministic, fast, pure-Python mapping keyed off the classified intent —
no model call. It returns 2-4 short, natural follow-up prompts.
"""

from __future__ import annotations

# Keyed by the fine-grained intents from ``classify.Intent``. Intents that share
# follow-ups (e.g. close/reopen variants) point at the same list.
_BY_INTENT: dict[str, list[str]] = {
    "close_road": [
        "Compare this to baseline",
        "What happens if I reopen it?",
        "Where does traffic divert?",
    ],
    "close_segment": [
        "Compare this to baseline",
        "What happens if I reopen it?",
        "Where does traffic divert?",
    ],
    "reopen_road": [
        "Compare this to baseline",
        "What happens if I reopen it?",
        "Where does traffic divert?",
    ],
    "reopen_segment": [
        "Compare this to baseline",
        "What happens if I reopen it?",
        "Where does traffic divert?",
    ],
    "change_capacity": [
        "Compare to baseline",
        "Try a bigger reduction",
        "Where does it back up?",
    ],
    "query_congestion": [
        "Why is the worst road congested?",
        "Ease congestion there",
        "Show me rush hour",
    ],
    "explain": [
        "Close that road",
        "Show it on the map",
        "What's the capacity?",
    ],
    "inspect": [
        "Why is it congested?",
        "Halve its capacity",
        "Compare to baseline",
    ],
    "optimize": [
        "Apply the plan",
        "Try a different objective",
        "Compare to baseline",
    ],
    "mitigate": [
        "Apply the plan",
        "Try a different objective",
        "Compare to baseline",
    ],
    "investigate": [
        "Apply the plan",
        "Try a different objective",
        "Compare to baseline",
    ],
    "focus": [
        "Where is congestion worst?",
        "Close a road here",
    ],
    "set_time": [
        "Where is congestion worst?",
        "Close a road here",
    ],
    "chat": [
        "Where is congestion worst right now?",
        "Close a road",
        "What can you do?",
    ],
}

_DEFAULT: list[str] = [
    "Where is congestion worst right now?",
    "Close a road",
    "What can you do?",
]


def followups(prompt: str, reply: str, intent: str) -> list[str]:
    """Return 2-4 short follow-up prompts for the given ``intent``.

    Heuristic and fast — a pure-Python mapping, no model call. ``prompt`` and
    ``reply`` are accepted for future grounding but the mapping is intent-keyed.
    """
    return list(_BY_INTENT.get(intent, _DEFAULT))
