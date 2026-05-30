"""Copilot tool-call schemas (P09) — shared with the API (api.schemas).

The model emits a ``ToolCall`` (a JSON object the API can validate and apply).
``Intervention`` is imported from ``api.schemas`` so there is a single source of
truth between the copilot and the backend.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..api.schemas import Intervention

ToolName = Literal[
    "preview_intervention",
    "create_scenario",
    "run_simulation",
    "compare_scenarios",
    "retrieve_policy",
    "explain_edge",
    "refuse",
]


class Citation(BaseModel):
    ref: str
    note: str


class ToolCall(BaseModel):
    tool: ToolName
    interventions: list[Intervention] = Field(default_factory=list)
    rationale: str = ""
    citations: list[Citation] = Field(default_factory=list)
    # Guardrail: every state-changing call must be confirmed via /preview first.
    requires_user_confirmation: bool = True
    blocked: bool = False
    summary: Optional[str] = None


def tool_call_json_schema() -> dict:
    """The JSON Schema handed to Ollama's ``format=`` for constrained decoding."""
    return ToolCall.model_json_schema()
