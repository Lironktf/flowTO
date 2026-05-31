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
    # Demand-side op (front-end wiring): injects/relieves trips around an anchor
    # node BEFORE OD generation — see model/demand_surge.py. Not a graph
    # mutation, so it is exempt from the edge-existence validation in app.py.
    "demand_change",
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
    # demand_change fields: anchor (edge_id and/or lng/lat) + a signed amount
    # that radiates along the chosen compass directions. `amount` is signed
    # (negative = relief); `mode` is "absolute" (trips) or "relative" (fraction).
    directions: Optional[list[str]] = None
    amount: Optional[float] = None
    mode: Optional[str] = None
    lng: Optional[float] = None
    lat: Optional[float] = None

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


class SimulateRequest(BaseModel):
    """A stateless, param-driven run: predict demand for ``time_context`` with the
    chosen model, apply the user's modifications, then simulate. Result is cached
    on (demand_model, time_context, interventions) — see api/recompute.py.
    """

    demand_model: Literal["xgboost", "gnn"] = "xgboost"
    time_context: dict = Field(default_factory=dict)  # weather forced to "clear" server-side
    interventions: list[Intervention] = Field(default_factory=list)
    iterations: int = 4


class SimulateResult(BaseModel):
    records: list[list]  # Record5 rows [edge_idx, load, speed, pressure, closure]
    summary: dict
    rgap: Optional[float] = None
    # Which demand model actually produced this — guards the silent heuristic
    # fallback (e.g. "XGBRegressor(...)", "gnn", or "HeuristicDemandModel").
    model_actual: str = ""
    cached: bool = False


class CompareResult(BaseModel):
    scenario_id: str
    against: str
    summary_delta: dict
    most_impacted_edges: list[dict]


class PreviewResult(BaseModel):
    scenario_id: str
    summary: dict
    mutated: bool = False
