"""Constrained tool-call generation + validation + re-ask loop (P09).

``plan()`` asks the model (Ollama, injected) for a JSON ``ToolCall`` constrained
by the Pydantic schema, validates it, runs **semantic checks** (edge_ids exist;
hard constraints), and re-asks (≤3) feeding the error back. The model call is
injected so tests run without a live model; on the Spark it's Nemotron via
Ollama with ``think=False`` + ``format=<schema>`` (per the memory note).
"""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import ValidationError

from .constraints import check_request
from .tools import Citation, ToolCall, tool_call_json_schema

# A model call takes (system, prompt, json_schema) and returns the raw JSON text.
ModelCall = Callable[[str, str, dict], str]

SYSTEM = (
    "You are a Toronto city-planning copilot. Convert the planner's request into a single "
    "JSON ToolCall against the scenario API. You are read-only by default: any state-changing "
    "action must set requires_user_confirmation=true and go through preview. Only reference "
    "edge_ids that exist. Cite the bylaw/policy constraints you preserved. If the request "
    "breaches a hard constraint, set tool='refuse' and blocked=true with citations."
)


class PlanError(RuntimeError):
    pass


def _valid_edge_ids(state) -> set:
    return set(getattr(state, "edge_index", {}) or {})


def plan(
    prompt: str,
    state,
    *,
    model_call: ModelCall,
    max_retries: int = 3,
) -> ToolCall:
    """NL → validated ToolCall. Raises ``PlanError`` if it can't validate."""
    schema = tool_call_json_schema()
    valid_edges = _valid_edge_ids(state)
    error_note = ""
    last_exc: Exception | None = None

    for _ in range(max_retries):
        raw = model_call(SYSTEM + error_note, prompt, schema)
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
            error_note = f"\nUnknown edge_ids {unknown}; only use edges that exist."
            last_exc = PlanError(f"unknown edge_ids {unknown}")
            continue

        # Hard-constraint check: refuse if breached.
        violations = check_request(prompt, [iv.to_op() for iv in call.interventions])
        if violations:
            return ToolCall(
                tool="refuse",
                blocked=True,
                requires_user_confirmation=False,
                rationale="Request breaches a hard constraint and was refused.",
                citations=[Citation(ref=v.ref, note=v.note) for v in violations],
            )

        # State-changing calls must require confirmation (preview-before-apply).
        if call.interventions and not call.blocked:
            call.requires_user_confirmation = True
        return call

    raise PlanError(f"could not produce a valid tool call: {last_exc}")
