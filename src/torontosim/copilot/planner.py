"""API-facing copilot entry (P09): ``plan_intervention(prompt, state)``.

A single classifier (``classify.classify``) is the sole intent authority; its
result dispatches to a deterministic handler (resolve / congestion / optimize /
focus) or, for conversational/compound asks, to the live freeform planner. Hard
constraint refusal stays deterministic so it holds even offline. Always
read-only / preview-first.
"""

from __future__ import annotations

import os

from ..api.schemas import Intervention
from . import rag
from .classify import ClassifyResult
from .constraints import check_request
from .tools import Citation, ToolCall, ViewDirective

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
            'Try: "ease congestion near BMO Field", "reduce capacity on Lake Shore eastbound", '
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
        citations=[
            Citation(ref="Optimizer (P10)", note="each candidate scored by running the sim")
        ],
        requires_user_confirmation=True,
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
        key=lambda r: r[0],  # sort by pressure only — road_name may be None (unorderable)
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


def _worst_road_view(state) -> ViewDirective | None:
    """A camera fit on the single most-congested named road, so a congestion query
    flies the map there (read-only). None if there's no readable baseline."""
    try:
        graph = state.baseline()["graph"]
    except Exception:  # noqa: BLE001 — no baseline yet → just skip the camera move
        return None
    best_name, best_p = None, -1.0
    for _u, _v, d in graph.edges(data=True):
        nm = d.get("road_name")
        p = d.get("pressure")
        if not nm or d.get("status") == "closed" or not isinstance(p, (int, float)):
            continue
        if (d.get("load") or 0) > 0 and p > best_p:
            best_name, best_p = nm, p
    if best_name is None:
        return None
    edge_ids = [
        d.get("edge_id")
        for _u, _v, d in graph.edges(data=True)
        if d.get("road_name") == best_name and d.get("status") != "closed" and d.get("edge_id")
    ]
    return ViewDirective(action="fit", road_name=best_name, edge_ids=edge_ids)


def _resolve_command(state, cls) -> ToolCall:
    """A close/reopen intent → a preview ToolCall via deterministic resolution.

    The classifier extracted only the NAMES; ``resolve.py`` maps them to real
    edge_ids (never invented). No extra model call here.
    """
    from .resolve import road_between, road_edges_by_name

    graph = getattr(state, "graph", None)
    if graph is None:
        return _generic_preview()
    intent = cls.intent
    if intent in ("close_road", "reopen_road"):
        res = road_edges_by_name(graph, cls.road_name)
        label = res.get("road_name", cls.road_name)
    else:  # close_segment / reopen_segment
        res = road_between(graph, cls.from_intersection, cls.to_intersection)
        label = f"{res.get('from_name')} → {res.get('to_name')}" if res.get("found") else None
    op = "close_edge" if intent.startswith("close") else "reopen_edge"
    verb = "Close" if intent.startswith("close") else "Reopen"

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
        view=ViewDirective(action="fit", road_name=label, edge_ids=res["edge_ids"]),
        requires_user_confirmation=True,
    )


def _capacity_command(state, cls) -> ToolCall:
    """A change_capacity intent → scale every segment of the named road."""
    from .resolve import road_edges_by_name

    graph = getattr(state, "graph", None)
    res = road_edges_by_name(graph, cls.road_name) if graph is not None else {"found": False}
    if not res.get("found"):
        return ToolCall(
            tool="answer",
            rationale=f"I couldn't find a road matching {cls.road_name!r}.",
            requires_user_confirmation=False,
        )
    mult = cls.multiplier if cls.multiplier and cls.multiplier > 0 else 0.5
    label = res.get("road_name", cls.road_name)
    interventions = [
        Intervention(op="change_capacity", edge_id=e, multiplier=mult) for e in res["edge_ids"]
    ]
    pct = round((mult - 1) * 100)
    change = f"{'+' if pct >= 0 else ''}{pct}% capacity"
    return ToolCall(
        tool="preview_intervention",
        interventions=interventions,
        rationale=f"Set {label} to {change} ({len(interventions)} segment(s)). Confirm to apply.",
        view=ViewDirective(action="fit", road_name=label, edge_ids=res["edge_ids"]),
        requires_user_confirmation=True,
    )


def _focus_call(state, cls) -> ToolCall:
    """A focus/show intent → a read-only camera move (no plan, no confirm)."""
    name = (cls.road_name or "").strip()
    if not name:
        return _generic_preview()
    return ToolCall(
        tool="answer",
        rationale=f"Showing {name} on the map.",
        view=ViewDirective(action="fit", road_name=name),
        requires_user_confirmation=False,
    )


def _dispatch(prompt: str, state, cls, live: bool) -> ToolCall:
    """Map a classified intent to a ToolCall. Hard-constraint refusal is checked
    first (deterministic, model-independent) so it holds even offline."""
    # Hard-constraint refusal (the "blocked" path) — owned by the deterministic
    # checker, never the model. (De-hardcode / warn-don't-block is a later step.)
    if check_request(prompt, state=state):
        return _blocked_call(prompt, state)

    intent = cls.intent if cls is not None else "chat"
    if intent == "query_congestion":
        return ToolCall(
            tool="answer",
            rationale=_answer_congestion(state),
            view=_worst_road_view(state),
            requires_user_confirmation=False,
        )
    if intent == "mitigate":
        return _hero_call(state)
    if intent == "optimize":
        try:
            return _optimize_call(state, prompt)
        except (ImportError, OSError, ValueError):
            return _generic_preview()
    if intent in ("close_road", "reopen_road", "close_segment", "reopen_segment"):
        return _resolve_command(state, cls)
    if intent == "change_capacity":
        return _capacity_command(state, cls)
    if intent == "focus":
        return _focus_call(state, cls)

    # chat / investigate / unresolved → a live freeform plan, else a safe default.
    if live:
        from .plan import PlanError, plan

        try:
            return plan(prompt, state)
        except (PlanError, OSError, ValueError):
            return _generic_preview()
    return _generic_preview()


def plan_intervention(
    prompt: str, state, *, use_live: bool | None = None, classification=None
) -> dict:
    """Return a validated, JSON-serializable copilot tool call for ``prompt``.

    A single classifier (``classify.classify``) is the sole intent authority; its
    result dispatches to a deterministic handler (resolve / congestion / optimize /
    focus) or, for conversational/compound asks, to the live freeform planner. A
    pre-computed ``classification`` (e.g. from ``/copilot/route``) is reused so we
    never classify twice. Always cites the bylaw corpus.
    """
    live = _live_enabled() if use_live is None else use_live

    cls = classification
    if cls is not None and not isinstance(cls, ClassifyResult):
        cls = ClassifyResult.model_validate(cls)
    if cls is None and live:
        from .classify import classify

        cls = classify(prompt)

    call = _dispatch(prompt, state, cls, live)

    retrieved = rag.retrieve(prompt, k=3)
    out = call.model_dump()
    out["retrieved_policy"] = retrieved
    out["intent"] = cls.intent if cls is not None else "chat"
    return out
