"""API-facing copilot entry (P09): ``plan_intervention(prompt, state)``.

A deterministic router handles the two rehearsed demo intents (hero mitigation,
blocked closure) so the stage demo never depends on live decoding; arbitrary
prompts fall through to live Nemotron (Ollama) when reachable, and to a safe
generic preview otherwise. Always read-only / preview-first.
"""

from __future__ import annotations

import json
import os

from ..api.schemas import Intervention
from . import rag
from .constraints import check_request
from .resolve import road_between, road_edges_by_name
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


def _blocked_call(prompt: str) -> ToolCall:
    violations = check_request(prompt)
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


# Ollama endpoint + model are env-configurable so the API can run anywhere and
# point at the gx10's Ollama over Tailscale, and so a smaller/faster model can
# be swapped in for the structured-extraction work.
#   FLOWTO_OLLAMA_URL    e.g. http://100.124.76.16:11434  (default localhost)
#   FLOWTO_COPILOT_MODEL e.g. qwen2.5:7b-instruct          (default nemotron3:33b)
def _ollama_url() -> str:
    return os.environ.get("FLOWTO_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def _ollama_model() -> str:
    return os.environ.get("FLOWTO_COPILOT_MODEL", "nemotron3:33b")


def _ollama_model_call(system: str, prompt: str, schema: dict) -> str:  # pragma: no cover - Spark
    """Live model via Ollama. think=False + format=schema (constrained JSON)."""
    import urllib.request

    body = {
        "model": _ollama_model(),
        "system": system,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0},
        "keep_alive": "10m",
    }
    req = urllib.request.Request(
        f"{_ollama_url()}/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["response"]


# --- Intent router ---------------------------------------------------------- #
# The model classifies intent and extracts only NAMES; resolve.py does the exact
# graph work (name -> node/edges), so no edge_id is ever invented.
#   close_road / reopen_road       -> a whole named road ("Gardiner Expressway")
#   close_segment / reopen_segment -> between two intersections (from/to)
#   query_congestion               -> "where is congestion worst" (answered, read-only)
#   other                          -> fall through to the general planner
_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "close_road",
                "reopen_road",
                "close_segment",
                "reopen_segment",
                "query_congestion",
                "other",
            ],
        },
        "road_name": {"type": "string"},
        "from_intersection": {"type": "string"},
        "to_intersection": {"type": "string"},
    },
    "required": ["intent"],
}
_INTENT_SYSTEM = (
    "Classify the user's traffic request into one intent and extract the names it "
    "mentions. Intents: 'close_road'/'reopen_road' close or reopen an ENTIRE named "
    "road (put its name in 'road_name', e.g. 'Gardiner Expressway'); "
    "'close_segment'/'reopen_segment' act only between two intersections (put them in "
    "'from_intersection'/'to_intersection', e.g. 'Yonge & Bloor'); 'query_congestion' "
    "asks where traffic/congestion is worst; 'other' for anything else. Return JSON only."
)


def _answer_congestion(state) -> str:
    """Read the cached baseline and describe the most congested roads (read-only)."""
    try:
        graph = state.baseline()["graph"]
    except Exception as exc:  # noqa: BLE001
        return f"I couldn't read the current congestion state ({type(exc).__name__})."
    rows = sorted(
        (
            (d.get("pressure") or 0.0, d.get("road_name"))
            for _u, _v, d in graph.edges(data=True)
            if d.get("status") != "closed"
            and isinstance(d.get("pressure"), (int, float))
            and (d.get("load") or 0) > 0
        ),
        reverse=True,
    )
    seen: set = set()
    top: list = []
    for p, nm in rows:
        key = nm or f"_unnamed{len(top)}"
        if key in seen:
            continue
        seen.add(key)
        top.append((nm, p))
        if len(top) >= 5:
            break
    if not top:
        return "No roads are congested in the current baseline."
    parts = [f"{nm or 'an unnamed segment'} (v/c {p:.1f})" for nm, p in top]
    return "Congestion is worst on: " + "; ".join(parts) + "."


def _try_command(prompt: str, state, model_call) -> ToolCall | None:
    """Route the prompt to a ToolCall (close/reopen/query), or None to fall through.

    Resolution is deterministic; the model only classifies intent + parses names.
    """
    graph = getattr(state, "graph", None)
    if graph is None:
        return None
    try:
        cmd = json.loads(model_call(_INTENT_SYSTEM, prompt, _INTENT_SCHEMA))
    except Exception:  # noqa: BLE001 — model/parse failure -> not a command
        return None
    intent = str(cmd.get("intent", "other")).lower()

    if intent == "query_congestion":
        return ToolCall(
            tool="explain_edge",
            rationale=_answer_congestion(state),
            requires_user_confirmation=False,
        )

    if intent in ("close_road", "reopen_road"):
        res = road_edges_by_name(graph, cmd.get("road_name"))
        op = "close_edge" if intent == "close_road" else "reopen_edge"
        verb = "Close" if intent == "close_road" else "Reopen"
        label = res.get("road_name", cmd.get("road_name"))
    elif intent in ("close_segment", "reopen_segment"):
        res = road_between(graph, cmd.get("from_intersection"), cmd.get("to_intersection"))
        op = "close_edge" if intent == "close_segment" else "reopen_edge"
        verb = "Close" if intent == "close_segment" else "Reopen"
        label = f"{res.get('from_name')} → {res.get('to_name')}" if res.get("found") else None
    else:
        return None  # 'other' -> general planner

    if not res.get("found"):
        return ToolCall(
            tool="preview_intervention",
            rationale=f"I couldn't resolve that — {res.get('reason', 'unknown')}.",
            requires_user_confirmation=False,
        )
    interventions = [Intervention(op=op, edge_id=e) for e in res["edge_ids"]]
    return ToolCall(
        tool="preview_intervention",
        interventions=interventions,
        rationale=f"{verb} {label} ({len(interventions)} road segment(s)). Confirm to apply.",
        requires_user_confirmation=True,
    )


def plan_intervention(prompt: str, state, *, use_live: bool = False) -> dict:
    """Return a validated, JSON-serializable copilot tool call for ``prompt``.

    Deterministic for the rehearsed intents; cites the relevant bylaw corpus via
    RAG. ``use_live=True`` routes unknown prompts to live Nemotron (Spark).
    """
    text = (prompt or "").lower()

    # 1) Hard-constraint refusal (the "blocked" demo path).
    if check_request(prompt):
        call = _blocked_call(prompt)
    # 2) Hero mitigation intent (ease/mitigate gridlock / post-match egress).
    elif any(kw in text for kw in ("ease", "mitigat", "gridlock", "post-match", "egress")):
        call = _hero_call()
    elif use_live:
        # Try the "close/reopen road from X to Y" command first (name→edges,
        # deterministic). Fall through to the general planner for anything else.
        call = _try_command(prompt, state, _ollama_model_call)
        if call is None:
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
