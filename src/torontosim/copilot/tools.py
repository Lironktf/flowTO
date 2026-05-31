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
    "answer",  # conversational reply (no plan) — small talk / can't act
]


class Citation(BaseModel):
    ref: str
    note: str


class Warning(BaseModel):
    """A severity-coded advisory shown in the warnings panel / chat (warn-don't-block).

    Mirrors the frontend ``Warning`` shape so the same object renders as a colored
    ``.warn-row``. Populated by the SSOT assess pass; carried on every ToolCall so
    the response contract is settled in one place.
    """

    severity: Literal["info", "warn", "danger"] = "warn"
    title: str = ""
    detail: str = ""
    ref: Optional[str] = None


class ViewDirective(BaseModel):
    """A read-only camera / timeline move the frontend executes (no confirm).

    The backend emits the target by NAME (or resolved edge_ids); the frontend turns
    that into the actual deck.gl camera transition via its local graph/search index.
    """

    action: Literal["fit", "fly", "select", "recenter", "tilt", "time"]
    road_name: Optional[str] = None
    edge_ids: list[str] = Field(default_factory=list)
    lng: Optional[float] = None
    lat: Optional[float] = None
    zoom: Optional[float] = None
    minute: Optional[int] = None  # action="time": minute-of-day (0–1440) to scrub to


class ToolCall(BaseModel):
    tool: ToolName
    interventions: list[Intervention] = Field(default_factory=list)
    rationale: str = ""
    citations: list[Citation] = Field(default_factory=list)
    # Severity-coded advisories (warn-don't-block) — never refuse, surface as warnings.
    warnings: list[Warning] = Field(default_factory=list)
    # Optional read-only camera/timeline move the frontend executes after the reply.
    view: Optional[ViewDirective] = None
    # Guardrail: every state-changing call must be confirmed via /preview first.
    requires_user_confirmation: bool = True
    blocked: bool = False
    summary: Optional[str] = None


def tool_call_json_schema() -> dict:
    """The JSON Schema handed to Ollama's ``format=`` for constrained decoding."""
    return ToolCall.model_json_schema()
