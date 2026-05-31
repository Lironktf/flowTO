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
from . import ollama_client, rag
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


def _resolve_edges(state, name_substr: str, limit: int = 2) -> list[str]:
    """Edge ids whose road name contains ``name_substr`` (live graph only)."""
    out: list[str] = []
    if state is None or not hasattr(state, "graph"):
        return out
    sub = name_substr.lower()
    for _u, _v, d in state.graph.edges(data=True):
        if sub in (d.get("road_name") or "").lower():
            eid = d.get("edge_id") or d.get("id")
            if eid is not None:
                out.append(eid)
        if len(out) >= limit:
            break
    return out


def _hero_interventions(state) -> list[Intervention]:
    """The rehearsed mitigation as concrete, applyable ops (resolved on the graph)."""
    ivs: list[Intervention] = []
    for name, mult in (("Dufferin", 0.7), ("Strachan", 0.7)):
        for eid in _resolve_edges(state, name):
            ivs.append(Intervention(op="change_capacity", edge_id=eid, multiplier=mult))
    for eid in _resolve_edges(state, "Princes"):
        ivs.append(Intervention(op="close_edge", edge_id=eid))
    return ivs


def _hero_call(state=None) -> ToolCall:
    return ToolCall(
        tool="preview_intervention",
        interventions=_hero_interventions(state),
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


def _live_enabled() -> bool:
    """Live Nemotron is on when TS_COPILOT_LIVE is truthy (default: on)."""
    return os.environ.get("TS_COPILOT_LIVE", "1").lower() not in ("0", "false", "no", "")


def _generic_preview() -> ToolCall:
    # Reached when nothing actionable could be parsed (e.g. small talk). Be
    # honest + helpful instead of staging an empty "preview".
    return ToolCall(
        tool="answer",
        rationale=(
            "I'm the planning copilot — I turn plain-English requests into traffic interventions. "
            "Try: \"ease congestion near BMO Field\", \"reduce capacity on Lake Shore eastbound\", "
            "or ask why a corridor is congested."
        ),
        requires_user_confirmation=False,
    )


def _optimize_call(state, prompt: str) -> ToolCall:
    """Invoke the P10 optimizer and return its sim-verified plan as a preview."""
    from ..optimizer.heuristic import propose

    payload = {"objective": "average_pressure", "max_actions": 3}
    result = propose(state, payload)
    plan = result.get("plan", [])
    if not plan:
        return ToolCall(
            tool="preview_intervention",
            rationale="The optimizer found no action that improves on doing nothing here.",
            requires_user_confirmation=False,
        )
    base, best = result.get("baseline_metric"), result.get("best_metric")
    delta = f"{base:.3f} → {best:.3f}" if isinstance(base, (int, float)) else "improved"
    return ToolCall(
        tool="preview_intervention",
        interventions=[Intervention.model_validate(iv) for iv in plan],
        rationale=(
            f"Optimizer scored candidate actions by simulating each; best sim-verified plan is "
            f"{len(plan)} action(s), average network pressure {delta}. Confirm to apply and run."
        ),
        citations=[Citation(ref="Optimizer (P10)", note="each candidate scored by running the sim")],
        requires_user_confirmation=True,
    )


# --- Intent router (adapted from PR #31) ------------------------------------ #
# The model classifies intent and extracts only NAMES; resolve.py does the exact
# graph work (name → node/edges), so no edge_id is ever invented. Whole-road and
# A→B segment closures + a read-only congestion query.
_COMMAND_HINTS = ("close", "reopen", "shut", "block", "congest", "worst", "bottleneck", "busiest", "between")
_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["close_road", "reopen_road", "close_segment", "reopen_segment", "query_congestion", "other"],
        },
        "road_name": {"type": "string"},
        "from_intersection": {"type": "string"},
        "to_intersection": {"type": "string"},
    },
    "required": ["intent"],
}
_INTENT_SYSTEM = (
    "Classify the user's traffic request into one intent and extract the names it mentions. "
    "Intents: 'close_road'/'reopen_road' act on an ENTIRE named road (put its name in 'road_name', "
    "e.g. 'Gardiner Expressway'); 'close_segment'/'reopen_segment' act only between two intersections "
    "(put them in 'from_intersection'/'to_intersection', e.g. 'Yonge & Bloor'); 'query_congestion' asks "
    "where traffic is worst; 'other' for anything else. Return JSON only."
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
    """Route close/reopen/query intents to a ToolCall via deterministic resolution.

    The model only classifies intent + parses names; ``resolve.py`` maps names to
    real edge_ids (never invented). Returns None to fall through to the planner.
    """
    from .resolve import road_between, road_edges_by_name

    graph = getattr(state, "graph", None)
    if graph is None:
        return None
    try:
        cmd = json.loads(model_call(_INTENT_SYSTEM, prompt, _INTENT_SCHEMA))
    except Exception:  # noqa: BLE001 — model/parse failure → not a command
        return None
    intent = str(cmd.get("intent", "other")).lower()

    if intent == "query_congestion":
        return ToolCall(tool="answer", rationale=_answer_congestion(state), requires_user_confirmation=False)

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
        return None  # 'other' → general planner

    if not res.get("found"):
        return ToolCall(
            tool="answer",
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


def plan_intervention(prompt: str, state, *, use_live: bool | None = None) -> dict:
    """Return a validated, JSON-serializable copilot tool call for ``prompt``.

    The two rehearsed intents (blocked closure, hero mitigation) resolve
    deterministically as a stage safety net; everything else goes to live
    Nemotron when enabled (``TS_COPILOT_LIVE``, default on), degrading to a safe
    generic preview if the model is unreachable. Always cites the bylaw corpus.
    """
    text = (prompt or "").lower()
    live = _live_enabled() if use_live is None else use_live

    # 1) Hard-constraint refusal (the "blocked" demo path).
    if check_request(prompt, state=state):
        call = _blocked_call(prompt, state)
    # 2) Hero mitigation intent (ease/mitigate gridlock / post-match egress).
    elif any(kw in text for kw in ("ease", "mitigat", "gridlock", "post-match", "egress")):
        call = _hero_call(state)
    # 3) Optimizer intent — let cuOpt/heuristic search propose the plan.
    elif any(kw in text for kw in ("optimize", "optimise", "optimal", "best plan", "recommend a plan")):
        try:
            call = _optimize_call(state, prompt)
        except (ImportError, OSError, ValueError):
            call = _generic_preview()
    elif live:
        from .plan import PlanError, plan

        call = None
        # Close/reopen a road or A→B segment, or "where's congestion?" — the model
        # only classifies + names, resolve.py maps to real edges (no hallucination).
        if any(h in text for h in _COMMAND_HINTS):
            try:
                call = _try_command(prompt, state, ollama_client.generate)
            except (OSError, ValueError):
                call = None
        if call is None:
            try:
                call = plan(prompt, state)
            except (PlanError, OSError, ValueError):
                call = _generic_preview()  # model unreachable / no valid call → safe default
    else:
        call = _generic_preview()

    # Attach top RAG citations (grounding) if the call didn't carry its own.
    retrieved = rag.retrieve(prompt, k=3)
    out = call.model_dump()
    out["retrieved_policy"] = retrieved
    return out
