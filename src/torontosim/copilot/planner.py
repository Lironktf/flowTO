"""API-facing copilot entry (P09): ``plan_intervention(prompt, state)``.

A single classifier (``classify.classify``) is the sole intent authority; its
result dispatches to a deterministic handler (resolve / congestion / optimize /
focus) or, for conversational/compound asks, to the live freeform planner. Hard
constraint refusal stays deterministic so it holds even offline. Always
read-only / preview-first.
"""

from __future__ import annotations

import os
import re

from ..api.schemas import Intervention
from . import rag
from .classify import ClassifyResult
from .tools import Citation, ToolCall, ViewDirective

# Referential phrases that mean "the worst / busiest road" rather than a named one.
# The classifier is told to emit road_name='worst' for these, but real models still
# sometimes echo the surface phrase ('the worst road') or a bare generic noun, so we
# match defensively here and resolve to the actual most-congested road below.
_SUPERLATIVE_RE = re.compile(
    r"\b(worst|most\s+congested|busiest|most\s+traffic|most\s+jammed|"
    r"heaviest|most\s+gridlock(?:ed)?)\b",
    re.I,
)
_GENERIC_NOUNS = {"street", "road", "the road", "the street", "worst", "the worst"}


def _is_superlative_ref(text: str) -> bool:
    """True if ``text`` refers to 'the worst/busiest road' instead of a named one."""
    t = (text or "").strip().lower()
    if not t:
        return False
    return bool(_SUPERLATIVE_RE.search(t)) or t in _GENERIC_NOUNS


# Deterministic minute-of-day parse for set_time, so the time never depends on the
# model doing clock arithmetic (which it does unreliably — temperature 0 isn't
# perfectly deterministic on GPU, so 'show me 6am' would sometimes fall back to the
# 5pm default). Named periods first (specific before generic), then a clock match.
_NAMED_MINUTES: list[tuple[tuple[str, ...], int]] = [
    (("midnight",), 0),
    (("noon", "midday", "mid-day"), 720),
    (("morning rush", "morning peak", "am peak", "am rush"), 480),
    (("evening rush", "evening peak", "pm peak", "pm rush", "rush hour", "rush-hour"), 1020),
    (("overnight", "late night", "late-night"), 180),
    (("morning",), 480),
    (("afternoon",), 900),
    (("evening",), 1020),
    (("tonight",), 1320),
]
_CLOCK_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", re.I)


def _parse_minute(prompt: str) -> int | None:
    """Minute-of-day (0–1439) from free text, or None if no time is mentioned.

    Handles named periods ('midnight', 'rush hour', 'morning') and clock times
    ('6 am', '8am', '14:30', '12pm')."""
    t = (prompt or "").lower()
    for keys, mins in _NAMED_MINUTES:
        if any(k in t for k in keys):
            return mins
    for m in _CLOCK_RE.finditer(t):
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        if hh > 24 or mm >= 60:
            continue
        ap = (m.group(3) or "").replace(".", "")
        if ap == "am":
            return ((0 if hh == 12 else hh) % 24) * 60 + mm
        if ap == "pm":
            return ((hh if hh == 12 else hh + 12) % 24) * 60 + mm
        if m.group(2) is not None:  # explicit "HH:MM" with no am/pm → 24-hour clock
            return (hh % 24) * 60 + mm
        # a bare number with no colon and no am/pm is too ambiguous — skip it
    return None


def _live_enabled() -> bool:
    """Live Nemotron is on when TS_COPILOT_LIVE is truthy (default: on)."""
    return os.environ.get("TS_COPILOT_LIVE", "1").lower() not in ("0", "false", "no", "")


def _generic_preview() -> ToolCall:
    """Honest fallback when nothing actionable could be produced (model unreachable
    or non-actionable input). No rehearsed examples — just a plain hint."""
    return ToolCall(
        tool="answer",
        rationale=(
            "I couldn't turn that into a concrete action. Name a specific road or "
            "intersection, or ask where congestion is worst."
        ),
        requires_user_confirmation=False,
    )


def suggested_prompts(state, n: int = 4) -> list[str]:
    """Example chips grounded in the REAL graph (no hardcoded road names). Picks
    the most-segmented major arterials (the recognizable long roads) so the chips
    reflect this city's network, not a rehearsed script."""
    base = ["Where is congestion worst right now?"]
    graph = getattr(state, "graph", None)
    if graph is None:
        return base
    from collections import Counter

    counts: Counter = Counter()
    for _u, _v, d in graph.edges(data=True):
        nm = d.get("road_name")
        if nm and d.get("road_class") in {"motorway", "trunk", "primary"}:
            counts[nm] += 1
    top = [nm for nm, _c in counts.most_common(6)]
    out = list(base)
    templates = ["What happens if I close {}?", "Show me {}", "Halve capacity on {}"]
    for tmpl, name in zip(templates, top):
        out.append(tmpl.format(name))
    return out[:n]


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


def _worst_congested_road_name(state) -> str | None:
    """Name of the single most-congested road in the baseline (None if unreadable)."""
    view = _worst_road_view(state)
    return view.road_name if view is not None else None


def _segments_for_road(graph, road_name) -> dict | None:
    """Resolve a road name to its matched name + segment data + edge_ids."""
    from .resolve import road_edges_by_name

    res = road_edges_by_name(graph, road_name)
    if not res.get("found"):
        return None
    name = res["road_name"]
    segs, eids = [], []
    for _u, _v, d in graph.edges(data=True):
        if d.get("road_name") == name:
            segs.append(d)
            if d.get("edge_id"):
                eids.append(d["edge_id"])
    return {"name": name, "segs": segs, "edge_ids": eids}


def _read_graph(state):
    """Prefer the cached baseline (has live pressure/load); else the static graph."""
    try:
        return state.baseline()["graph"]
    except Exception:  # noqa: BLE001
        return getattr(state, "graph", None)


def _inspect_road(state, cls) -> ToolCall:
    """Flat stats for a named road (read-only)."""
    graph = _read_graph(state)
    if graph is None:
        return _generic_preview()
    info = _segments_for_road(graph, cls.road_name)
    if info is None:
        return ToolCall(
            tool="answer",
            rationale=f"I couldn't find a road matching {cls.road_name!r}.",
            requires_user_confirmation=False,
        )
    segs = info["segs"]
    cls_name = next((s.get("road_class") for s in segs if s.get("road_class")), "road")
    lanes = max((s.get("lanes") or 0) for s in segs) if segs else 0
    cap = sum((s.get("capacity") or 0) for s in segs) / max(1, len(segs))
    pressures = [s.get("pressure") for s in segs if isinstance(s.get("pressure"), (int, float))]
    load = sum((s.get("load") or 0) for s in segs)
    closed = sum(1 for s in segs if s.get("status") == "closed")
    avg_p = sum(pressures) / len(pressures) if pressures else 0.0
    rationale = (
        f"{info['name']}: {cls_name}, {int(lanes)} lane(s), {len(segs)} segment(s)"
        + (f", {closed} closed" if closed else "")
        + f". Avg capacity ~{cap:.0f} veh/h; current v/c {avg_p:.2f}, load {load:.0f}."
    )
    return ToolCall(
        tool="answer",
        rationale=rationale,
        view=ViewDirective(action="fit", road_name=info["name"], edge_ids=info["edge_ids"]),
        requires_user_confirmation=False,
    )


def _explain_congestion(state, cls) -> ToolCall:
    """Explain WHY a named road is congested: binding constraint + top feeder roads."""
    graph = _read_graph(state)
    if graph is None:
        return _generic_preview()
    info = _segments_for_road(graph, cls.road_name)
    if info is None:
        return ToolCall(
            tool="answer",
            rationale=f"I couldn't find a road matching {cls.road_name!r}.",
            requires_user_confirmation=False,
        )
    name, segs = info["name"], info["segs"]
    pressures = [s.get("pressure") for s in segs if isinstance(s.get("pressure"), (int, float))]
    avg_p = sum(pressures) / len(pressures) if pressures else 0.0
    over = sum(1 for p in pressures if p > 1.0)
    load = sum((s.get("load") or 0) for s in segs)
    cap = sum((s.get("capacity") or 0) for s in segs) / max(1, len(segs))

    # Upstream feeders: roads whose edges flow INTO this road's nodes.
    road_nodes = {s.get("from_node") for s in segs} | {s.get("to_node") for s in segs}
    feeders: dict = {}
    for n in road_nodes:
        if n is None or n not in graph:
            continue
        for _u, _v, d in graph.in_edges(n, data=True):
            rn = d.get("road_name")
            if rn and rn != name:
                feeders[rn] = feeders.get(rn, 0.0) + (d.get("load") or 0.0)
    top = [r for r in sorted(feeders, key=lambda r: -feeders[r]) if feeders[r] > 0][:2]

    if avg_p < 0.5 and not over:
        why = f"{name} isn't congested right now (v/c {avg_p:.2f})."
    else:
        binding = "demand exceeds its capacity" if load > cap else "it's near capacity"
        why = (
            f"{name} is congested (v/c {avg_p:.2f}"
            + (f", {over} segment(s) over capacity" if over else "")
            + f"): {binding} (load {load:.0f} vs ~{cap:.0f} veh/h)."
        )
        if top:
            why += " Most inflow comes from " + " and ".join(top) + "."
    return ToolCall(
        tool="answer",
        rationale=why,
        view=ViewDirective(action="fit", road_name=name, edge_ids=info["edge_ids"]),
        requires_user_confirmation=False,
    )


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
    """A focus/show intent → a read-only camera move (no plan, no confirm).

    Resolves the typed name to the canonical road + its edge_ids so the camera fits
    precisely and the segments highlight (a bare name like 'Gardiner' otherwise leaves
    the frontend to fuzzy-match with no ids to draw)."""
    name = (cls.road_name or "").strip()
    if not name:
        return _generic_preview()
    graph = _read_graph(state)
    info = _segments_for_road(graph, name) if graph is not None else None
    # Only frame a road when the match confidently covers what the user said. A
    # weak match ('Liberty Village' -> 'Liberty Street', 0.5) is almost certainly a
    # place, not that road — so we pass the raw name through (no edge_ids) and the
    # frontend's omnibox resolver geocodes it. This keeps navigation a single source
    # of truth: roads frame precisely, places fall through to the same geocoder the
    # search bar uses.
    if info is not None:
        from .resolve import distinctive_coverage

        if distinctive_coverage(name, info["name"]) >= 0.6:
            return ToolCall(
                tool="answer",
                rationale=f"Showing {info['name']} on the map.",
                view=ViewDirective(action="fit", road_name=info["name"], edge_ids=info["edge_ids"]),
                requires_user_confirmation=False,
            )
    # No confident road match → best-effort camera move by name; the frontend
    # resolves it (local roads, then Mapbox places).
    return ToolCall(
        tool="answer",
        rationale=f"Showing {name} on the map.",
        view=ViewDirective(action="fit", road_name=name),
        requires_user_confirmation=False,
    )


def _dispatch(prompt: str, state, cls, live: bool) -> ToolCall:
    """Map a classified intent to a ToolCall. Warn-don't-block: constraint conflicts
    are attached as severity-coded warnings (in plan_intervention), never refused."""
    intent = cls.intent if cls is not None else "chat"
    # Resolve superlative/referential road phrases ('the worst road', 'the busiest
    # street') to the actual most-congested road BEFORE the deterministic handlers run.
    # Otherwise resolve.py fuzzy-matches the literal word 'worst'/'street' and either
    # fails or lands on a nonsense road. This works with no conversation history.
    if (
        cls is not None
        and intent
        in {"close_road", "reopen_road", "change_capacity", "explain", "inspect", "focus"}
        and _is_superlative_ref(cls.road_name)
    ):
        worst = _worst_congested_road_name(state)
        if worst:
            cls = cls.model_copy(update={"road_name": worst})
    if intent == "query_congestion":
        return ToolCall(
            tool="answer",
            rationale=_answer_congestion(state),
            view=_worst_road_view(state),
            requires_user_confirmation=False,
        )
    if intent == "explain":
        return _explain_congestion(state, cls)
    if intent == "inspect":
        return _inspect_road(state, cls)
    # Both "make it better" intents go to the sim-verified optimizer — a real,
    # scored plan, not a rehearsed script. (mitigate folds into optimize.)
    if intent in ("optimize", "mitigate"):
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
    if intent == "set_time":
        from ..timeofday import clamp_minute_of_day, hhmm

        # Deterministic parse is authoritative (the model's clock math is flaky);
        # fall back to the model's minute, then to the 5pm peak default. Clamp to a
        # valid minute-of-day (never silently wrap an out-of-range value).
        parsed = _parse_minute(prompt)
        raw = parsed if parsed is not None else (cls.minute if cls.minute is not None else 1020)
        minute = clamp_minute_of_day(raw)
        return ToolCall(
            tool="answer",
            rationale=f"Showing the network at {hhmm(minute)}.",
            view=ViewDirective(action="time", minute=minute),
            requires_user_confirmation=False,
        )

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

    # Warn-don't-block: attach severity-coded warnings to any actionable plan
    # (the SSOT assess pass). The plan stays confirmable even with danger warnings.
    if call.interventions:
        from .assess import assess

        call.warnings = assess(call.interventions, state, prompt=prompt)

    retrieved = rag.retrieve(prompt, k=3)
    out = call.model_dump()
    out["retrieved_policy"] = retrieved
    out["intent"] = cls.intent if cls is not None else "chat"
    return out
