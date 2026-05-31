"""Pydantic schemas shared by the API and the copilot tool-call layer (P06/P09).

``Intervention`` mirrors ``graph.mutations`` ops so the copilot (P09) emits the
exact same objects the API validates and applies.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

InterventionType = Literal[
    "close_edge",
    "reopen_edge",
    "remove_edge",
    "change_capacity",
    "close_node",
    "add_edge",
]


class Intervention(BaseModel):
    op: InterventionType
    edge_id: Optional[str] = None
    node_id: Optional[int] = None
    multiplier: Optional[float] = None
    # add_edge fields
    from_node: Optional[int] = None
    to_node: Optional[int] = None
    road_name: Optional[str] = None
    speed_kmh: Optional[float] = None
    lanes: Optional[float] = None
    capacity: Optional[float] = None

    def to_op(self) -> dict:
        return self.model_dump(exclude_none=True)


class ScenarioCreate(BaseModel):
    name: str = Field(default="Untitled scenario")
    interventions: list[Intervention] = Field(default_factory=list)
    weather: str = "clear"
    time_context: dict = Field(default_factory=dict)


class Scenario(ScenarioCreate):
    id: str


class ScenarioPatch(BaseModel):
    name: Optional[str] = None
    interventions: Optional[list[Intervention]] = None
    weather: Optional[str] = None
    time_context: Optional[dict] = None


class RunRequest(BaseModel):
    engine: Literal["kpath", "equilibrium"] = "kpath"
    congestion_model: Literal["legacy", "bpr"] = "bpr"
    backend: Literal["cpu", "gpu"] = "cpu"
    recompute: Literal["full", "blast"] = "full"
    iterations: int = 4


class RunResult(BaseModel):
    scenario_id: str
    summary: dict
    engine: str
    congestion_model: str
    recompute: str
    blast_stats: Optional[dict] = None
    rgap: Optional[float] = None


class CompareResult(BaseModel):
    scenario_id: str
    against: str
    summary_delta: dict
    most_impacted_edges: list[dict]


class PreviewResult(BaseModel):
    scenario_id: str
    summary: dict
    mutated: bool = False


class CopilotConfirm(BaseModel):
    """Apply a previewed copilot tool call: create a scenario, run, compare, explain."""

    interventions: list[Intervention] = Field(default_factory=list)
    name: str = "Copilot scenario"
    # Blast-radius recompute by default: interactive (~1-2s vs ~60s full) and now
    # compared against the matching AON baseline, so the deltas are correct.
    run: RunRequest = Field(default_factory=lambda: RunRequest(recompute="blast"))


class CopilotConfirmResult(BaseModel):
    scenario_id: str
    summary: dict
    summary_delta: dict
    most_impacted_edges: list[dict]
    explanation: str
