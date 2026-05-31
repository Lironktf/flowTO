"""Bounded, read-only multi-tool agent loop (P09).

Nemotron drives a short chain of tools to answer a compound request — e.g.
*propose → simulate-on-scratch → compare → optimize → explain* — choosing the
next tool from intermediate results. Crucially this loop is **read-only**: it
runs hypothetical scenarios on throwaway state and NEVER mutates the committed
store. The terminal ``propose`` returns a plan that still goes through the
human-gated ``/copilot/confirm`` to actually apply. A hard ``max_steps`` cap
bounds latency and guarantees termination.

The model call is injectable so tests run without a live model; the default is
live Nemotron via ``ollama_client``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from ..api.schemas import Intervention
from . import ollama_client, rag
from .plan import candidate_edges, sanitize_interventions
from .tools import Citation, Warning

ModelCall = Callable[[str, str, dict], str]

AGENT_SYSTEM = (
    "You are a Toronto city-planning copilot working step by step. Each turn, emit ONE JSON action, "
    "then you will see its result and choose the next action. ALWAYS fill 'thought' with one short "
    "sentence about THIS specific step — what you are testing or concluding right now and why. Do "
    "NOT just restate the goal; reference the latest OBSERVATION when deciding the next step.\n"
    "If the message is a greeting, small talk, or a general question that is NOT a request to change "
    "the road network, use 'answer' to reply briefly and conversationally — do NOT invent "
    "interventions, edges, or bylaws.\n"
    "Read-only tools (use to investigate before proposing a network change):\n"
    "  - retrieve_policy: look up relevant bylaws. Set 'query'.\n"
    "  - simulate: run a hypothetical intervention set and see its effect vs baseline. Set 'interventions'.\n"
    "  - optimize: ask the optimizer for a sim-verified plan (no args).\n"
    "Terminal actions (end the task):\n"
    "  - propose: recommend a plan for the planner to confirm. Set 'interventions' + 'rationale'.\n"
    "  - answer: reply with information only (no plan). Set 'answer'.\n"
    "Use ONLY edge_ids from CANDIDATE EDGES. For capacity use op='change_capacity' + 'multiplier'. "
    "Investigate with simulate/optimize before you propose, but do NOT repeat an action you already "
    "ran (its result is in OBSERVATIONS). After one or two investigations, finish with 'propose' or "
    "'answer'. Do not invent bylaws or edge_ids."
)


class AgentStep(BaseModel):
    thought: str = ""
    tool: Literal["retrieve_policy", "simulate", "optimize", "propose", "answer"]
    query: Optional[str] = None
    interventions: list[Intervention] = Field(default_factory=list)
    rationale: str = ""
    answer: str = ""


class AgentResult(BaseModel):
    answer: str
    interventions: list[Intervention] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    steps: list[dict] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    blocked: bool = False


def _valid_edges(state) -> set:
    return set(getattr(state, "edge_index", {}) or {})


def _simulate(state, interventions: list[dict]) -> dict:
    """Run a hypothetical intervention set vs baseline — READ-ONLY (no store)."""
    from ..simulation.simulate_traffic import compare_simulations, simulate_scenario

    result = simulate_scenario(
        state.graph,
        state.od_matrix,
        interventions,
        iterations=4,
        weather=state.weather,
        time_context=state.time_context,
        engine="kpath",
        congestion_model="bpr",
        recompute="blast",
    )
    # Compare against the same-method (AON/blast) baseline when available, so the
    # agent's scratch deltas are correct AND fast (~1-2s vs ~60s full).
    base = state.blast_baseline() if hasattr(state, "blast_baseline") else state.baseline()
    diff = compare_simulations(base, result)
    return {
        "summary_delta": diff.get("summary_delta", {}),
        "most_impacted_edges": diff.get("most_impacted_edges", [])[:3],
    }


def _optimize(state) -> dict:
    from ..optimizer.heuristic import propose

    res = propose(state, {"objective": "average_pressure", "max_actions": 3})
    return {
        "plan": res.get("plan", []),
        "baseline_metric": res.get("baseline_metric"),
        "best_metric": res.get("best_metric"),
    }


def _default_model_call(system: str, prompt: str, schema: dict) -> str:
    return ollama_client.generate(system, prompt, schema)


def _transcript_block(steps: list[dict], remaining: int) -> str:
    head = (
        f"\nSTEPS REMAINING: {remaining} — finish with 'propose' or 'answer' before they run out."
    )
    if not steps:
        return head
    lines = [
        f"  step {i + 1}: {s['tool']} -> {json.dumps(s['observation'])[:300]}"
        for i, s in enumerate(steps)
    ]
    return head + "\nOBSERVATIONS SO FAR (do not repeat these):\n" + "\n".join(lines)


def _candidate_block(state, goal: str) -> str:
    cands = candidate_edges(state, goal)
    if not cands:
        return "\nCANDIDATE EDGES: none matched by name; do not invent edge_ids."
    return "\nCANDIDATE EDGES (use only these edge_ids):\n" + "\n".join(
        f"  {c['edge_id']}: {c['road_name']} ({c['road_class']})" for c in cands
    )


def _finalize_propose(goal: str, step: AgentStep, state, steps: list[dict]) -> AgentResult:
    ivs = sanitize_interventions(step.interventions, _valid_edges(state))
    # Warn-don't-block: the SSOT assess pass returns severity-coded warnings the
    # user can override — the agent never silently refuses a plan.
    from .assess import assess

    warnings = assess(ivs, state, prompt=goal) if ivs else []
    return AgentResult(
        answer=step.rationale or step.answer or "Proposed a plan — confirm to apply.",
        interventions=ivs,
        warnings=warnings,
        steps=steps,
        requires_user_confirmation=bool(ivs),
    )


def _require_thought(schema: dict) -> dict:
    """Mark 'thought' required so the model emits its reasoning each step."""
    req = schema.setdefault("required", [])
    if "thought" not in req:
        req.append("thought")
    return schema


def _open_schema() -> dict:
    return _require_thought(AgentStep.model_json_schema())


def _terminal_schema() -> dict:
    """AgentStep schema with the action enum restricted to terminal actions."""
    schema = AgentStep.model_json_schema()
    prop = schema.get("properties", {}).get("tool")
    if prop is not None:
        prop["enum"] = ["propose", "answer"]
    return _require_thought(schema)


def run_agent(
    goal: str, state, *, model_call: ModelCall | None = None, max_steps: int = 4
) -> AgentResult:
    """Drive a bounded, read-only tool chain to answer ``goal``.

    The last step is forced terminal (schema restricted to propose/answer) so the
    loop always converges to a plan or an answer instead of investigating forever.
    """
    model_call = model_call or _default_model_call
    open_schema = _open_schema()
    term_schema = _terminal_schema()
    steps: list[dict] = []
    seen: dict = {}  # (tool, args) → observation, to skip repeated identical work

    for i in range(max_steps):
        remaining = max_steps - i
        final = remaining == 1
        system = AGENT_SYSTEM + _candidate_block(state, goal) + _transcript_block(steps, remaining)
        if final:
            system += "\nThis is your LAST step: you MUST 'propose' a plan or 'answer' now."
        try:
            step = AgentStep.model_validate_json(
                model_call(system, goal, term_schema if final else open_schema)
            )
        except (ValidationError, json.JSONDecodeError, OSError, ValueError, KeyError):
            break  # invalid output or model unreachable → forced summary

        if step.tool == "answer":
            steps.append({"tool": "answer", "thought": step.thought, "observation": step.answer})
            return AgentResult(answer=step.answer or "Done.", steps=steps)
        if step.tool == "propose":
            steps.append(
                {"tool": "propose", "thought": step.thought, "observation": "proposed a plan"}
            )
            return _finalize_propose(goal, step, state, steps)
        # Dedup: if the model re-runs an identical tool call, reuse the cached
        # observation and nudge it to pick a different action (saves a sim/optimize).
        key = None
        if step.tool == "retrieve_policy":
            key = ("retrieve_policy", step.query or goal)
            obs = seen[key] if key in seen else rag.retrieve(step.query or goal, k=3)
        elif step.tool == "simulate":
            clean = sanitize_interventions(step.interventions, _valid_edges(state))
            if not clean:
                obs = {"error": "no valid edge_id in the proposed interventions"}
            else:
                ops = [iv.to_op() for iv in clean]
                key = ("simulate", json.dumps(ops, sort_keys=True))
                obs = seen[key] if key in seen else _simulate(state, ops)
        elif step.tool == "optimize":
            key = ("optimize", "")
            obs = seen[key] if key in seen else _optimize(state)
        else:  # pragma: no cover — schema-constrained
            break
        repeated = key is not None and key in seen
        if key is not None:
            seen[key] = obs
        thought = step.thought + (
            " [repeat — prior result reused; try a different action or finish]" if repeated else ""
        )
        steps.append({"tool": step.tool, "thought": thought, "observation": obs})

    # Step cap or parse failure: summarize what we learned, no plan committed.
    return AgentResult(
        answer="Reached the investigation step limit; review the observations and ask me to propose a plan.",
        steps=steps,
    )
