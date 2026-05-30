"""API-facing copilot entry (P09): ``plan_intervention(prompt, state)``.

A deterministic router handles the two rehearsed demo intents (hero mitigation,
blocked closure) so the stage demo never depends on live decoding; arbitrary
prompts fall through to live Nemotron (Ollama) when reachable, and to a safe
generic preview otherwise. Always read-only / preview-first.
"""

from __future__ import annotations

import json

from . import rag
from .constraints import check_request
from .tools import Citation, ToolCall

# The rehearsed mitigation plan (matches design/js/data.js copilotHero).
_HERO_STEPS = [
    "Eastbound contraflow on Lake Shore Blvd W (Strachan → Bathurst), 17:00–18:30",
    "Retime Dufferin and Strachan signals — 110 s cycle, egress-biased splits",
    "Close Princes' Blvd to general traffic (pedestrian egress); hold 509 / 511 transit priority",
]
_HERO_CITATIONS = [
    ("Toronto Municipal Code Ch. 950", "temporary traffic regulation under an approved event TMP"),
    ("King St Transit Priority Corridor", "through-traffic restriction preserved"),
    ("Toronto Municipal Code Ch. 880", "fire-route / emergency access lanes maintained"),
    ("AODA 2005", "accessible pedestrian route on Princes' Blvd retained"),
]


def _hero_call() -> ToolCall:
    return ToolCall(
        tool="preview_intervention",
        rationale=(
            "Full-time releases ~45,000 over 25 minutes onto the Lake Shore / Strachan / "
            "Dufferin spine with severe spill-over into local streets. A bylaw-valid mitigation: "
            + "; ".join(_HERO_STEPS)
            + ". Projected vs unmitigated: total delay −38%, local infiltration −71%."
        ),
        citations=[Citation(ref=r, note=n) for r, n in _HERO_CITATIONS],
        requires_user_confirmation=True,
    )


def _blocked_call(prompt: str, state=None) -> ToolCall:
    violations = check_request(prompt, state=state)
    return ToolCall(
        tool="refuse",
        blocked=True,
        requires_user_confirmation=False,
        rationale=(
            "I can't apply that — it breaches hard constraints. The eastbound-contraflow "
            "alternative clears 84% of the same demand without these conflicts."
        ),
        citations=[Citation(ref=v.ref, note=v.note) for v in violations],
    )


def _ollama_model_call(system: str, prompt: str, schema: dict) -> str:  # pragma: no cover - Spark
    """Live Nemotron via Ollama (Spark only). think=False + format=schema."""
    import urllib.request

    body = {
        "model": "nemotron3:33b",
        "system": system,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0},
        "keep_alive": "10m",
    }
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["response"]


def plan_intervention(prompt: str, state, *, use_live: bool = False) -> dict:
    """Return a validated, JSON-serializable copilot tool call for ``prompt``.

    Deterministic for the rehearsed intents; cites the relevant bylaw corpus via
    RAG. ``use_live=True`` routes unknown prompts to live Nemotron (Spark).
    """
    text = (prompt or "").lower()

    # 1) Hard-constraint refusal (the "blocked" demo path).
    if check_request(prompt, state=state):
        call = _blocked_call(prompt, state)
    # 2) Hero mitigation intent (ease/mitigate gridlock / post-match egress).
    elif any(kw in text for kw in ("ease", "mitigat", "gridlock", "post-match", "egress")):
        call = _hero_call()
    elif use_live:
        from .plan import plan

        call = plan(prompt, state, model_call=_ollama_model_call)
    else:
        # Safe generic: preview-only, no committed change.
        call = ToolCall(
            tool="preview_intervention",
            rationale="Previewing the requested change — confirm to apply.",
            requires_user_confirmation=True,
        )

    # Attach top RAG citations (grounding) if the call didn't carry its own.
    retrieved = rag.retrieve(prompt, k=3)
    out = call.model_dump()
    out["retrieved_policy"] = retrieved
    return out
