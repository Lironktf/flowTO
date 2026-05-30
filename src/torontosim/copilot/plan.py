"""Constrained tool-call generation + validation + re-ask loop (P09).

``plan()`` asks Nemotron (via Ollama) for a JSON ``ToolCall`` constrained by the
Pydantic schema, validates it, runs **semantic checks** (edge_ids exist; hard
bylaw constraints), and re-asks (≤3) feeding the error back. The model call is
injectable so tests run without a live model; the default routes to the live
Spark Nemotron through ``ollama_client`` (``think=False`` + ``format=<schema>``).

To keep emitted ``edge_id``s valid the system prompt is seeded with the graph
edges whose road name matches the request (a small candidate set, not all 18k).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from pydantic import ValidationError

from . import ollama_client, rag
from .constraints import advisories, check_request
from .tools import Citation, ToolCall, tool_call_json_schema

# A model call takes (system, prompt, json_schema) and returns the raw JSON text.
ModelCall = Callable[[str, str, dict], str]

# The model PROPOSES; a deterministic checker (check_request) OWNS refusal. We do
# not let the model self-refuse — left to its own devices it invents bylaws to
# justify refusing. So: always emit a concrete tool call from the real candidate
# edges, cite only from the provided bylaw context, never fabricate a citation.
SYSTEM = (
    "You are a Toronto city-planning copilot. Convert the planner's request into ONE concrete "
    "JSON ToolCall (preview_intervention or create_scenario) against the scenario API, using "
    "ONLY edge_ids from CANDIDATE EDGES below.\n"
    "Intervention ops:\n"
    "  - change_capacity: scale a road's capacity. Set 'multiplier' (0.5 = halve, 1.5 = add 50%).\n"
    "  - close_edge / reopen_edge / remove_edge: take an edge_id only.\n"
    "  - Do NOT use add_edge unless building a brand-new road (needs from_node/to_node).\n"
    "Always fill 'rationale' with one factual sentence. Do NOT refuse and do NOT invent bylaws "
    "or citations — a separate validator enforces legality; cite ONLY from RELEVANT BYLAWS."
)

_WORD = re.compile(r"[a-z]+")
_EDGE_OPS = {"close_edge", "reopen_edge", "remove_edge", "change_capacity"}


class PlanError(RuntimeError):
    pass


def sanitize_interventions(interventions, valid_edges: set | None = None) -> list:
    """Drop malformed ops the model sometimes emits (an edge op with no/unknown
    edge_id, or change_capacity with no multiplier) so they never reach the sim,
    which raises KeyError on a missing edge_id."""
    out = []
    for iv in interventions:
        op = getattr(iv, "op", None)
        if op in _EDGE_OPS:
            if not iv.edge_id:
                continue
            if valid_edges and iv.edge_id not in valid_edges:
                continue
            if op == "change_capacity" and iv.multiplier is None:
                continue
        out.append(iv)
    return out


def _valid_edge_ids(state) -> set:
    return set(getattr(state, "edge_index", {}) or {})


def _edge_meta(state) -> dict:
    out: dict = {}
    if state is None or not hasattr(state, "graph"):
        return out
    for _u, _v, d in state.graph.edges(data=True):
        eid = d.get("edge_id") or d.get("id")
        if eid is not None:
            out[eid] = {"road_name": d.get("road_name") or "", "road_class": d.get("road_class") or ""}
    return out


def candidate_edges(state, prompt: str, limit: int = 30) -> list[dict]:
    """Graph edges whose road name shares a word with the request (capped)."""
    meta = _edge_meta(state)
    words = {w for w in _WORD.findall((prompt or "").lower()) if len(w) > 3}
    scored: list[tuple[int, str, dict]] = []
    for eid, m in meta.items():
        name_words = set(_WORD.findall(m["road_name"].lower()))
        hits = len(words & name_words)
        if hits:
            scored.append((hits, eid, m))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"edge_id": eid, **m} for _h, eid, m in scored[:limit]]


def _candidate_block(candidates: list[dict]) -> str:
    if not candidates:
        return "\nCANDIDATE EDGES: none matched by name; do not invent edge_ids."
    lines = [f"  {c['edge_id']}: {c['road_name']} ({c['road_class']})" for c in candidates]
    return "\nCANDIDATE EDGES (use only these edge_ids):\n" + "\n".join(lines)


def _bylaw_block(prompt: str, k: int = 3) -> str:
    """Top-k bylaw titles as grounding so any citation is real, not invented."""
    try:
        hits = rag.retrieve(prompt, k=k)
    except Exception:  # noqa: BLE001 — corpus/retriever issues never block planning
        return ""
    if not hits:
        return ""
    lines = [f"  - {h['title']} ({h['source'].split('.')[0]})" for h in hits]
    return "\nRELEVANT BYLAWS (cite only from these):\n" + "\n".join(lines)


def _default_model_call(system: str, prompt: str, schema: dict) -> str:
    return ollama_client.generate(system, prompt, schema)


def plan(
    prompt: str,
    state,
    *,
    model_call: ModelCall | None = None,
    max_retries: int = 3,
) -> ToolCall:
    """NL → validated ToolCall. Raises ``PlanError`` if it can't validate."""
    model_call = model_call or _default_model_call
    schema = tool_call_json_schema()
    valid_edges = _valid_edge_ids(state)
    candidates = candidate_edges(state, prompt)
    system = SYSTEM + _candidate_block(candidates) + _bylaw_block(prompt)
    error_note = ""
    last_exc: Exception | None = None

    for _ in range(max_retries):
        raw = model_call(system + error_note, prompt, schema)
        try:
            data = json.loads(raw)
            call = ToolCall.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_exc = exc
            error_note = f"\nYour previous reply was invalid: {exc}. Return valid JSON only."
            continue

        # Semantic check: every referenced edge_id must exist in the graph.
        unknown = [
            iv.edge_id
            for iv in call.interventions
            if iv.edge_id is not None and valid_edges and iv.edge_id not in valid_edges
        ]
        if unknown:
            error_note = f"\nUnknown edge_ids {unknown}; only use edges from CANDIDATE EDGES."
            last_exc = PlanError(f"unknown edge_ids {unknown}")
            continue

        # Drop malformed ops (edge op with no edge_id, etc.) before anything runs.
        call.interventions = sanitize_interventions(call.interventions, valid_edges)

        # Hard-constraint check is the SOLE authority on refusal.
        violations = check_request(prompt, [iv.to_op() for iv in call.interventions], state)
        if violations:
            return ToolCall(
                tool="refuse",
                blocked=True,
                requires_user_confirmation=False,
                rationale="Request breaches a hard constraint and was refused.",
                citations=[Citation(ref=v.ref, note=v.note) for v in violations],
            )
        # The model is not allowed to self-refuse on invented grounds: if it
        # refused but nothing real is breached, force a concrete proposal.
        if call.tool == "refuse" or (
            call.tool in ("preview_intervention", "create_scenario") and not call.interventions
        ):
            error_note = (
                "\nDo not refuse and do not return an empty interventions list. Propose ONE "
                "concrete intervention using a CANDIDATE EDGE (e.g. change_capacity or close_edge)."
            )
            last_exc = PlanError("model refused without a real constraint")
            continue

        # State-changing calls must require confirmation (preview-before-apply).
        if call.interventions and not call.blocked:
            call.requires_user_confirmation = True
            # Surface soft, data-derived warnings as extra citations.
            for w in advisories(prompt, [iv.to_op() for iv in call.interventions], state):
                call.citations.append(Citation(ref=w.ref, note=w.note))
        return call

    raise PlanError(f"could not produce a valid tool call: {last_exc}")
