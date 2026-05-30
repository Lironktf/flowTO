"""Data-backed constraint checker (P09) — hard bylaw guardrails.

Runs BEFORE anything reaches the sim. A request that breaches a **hard**
constraint is refused with citations, the network unchanged (the "constraint-
blocked" demo state and the safety floor under the copilot).

Two information sources, so refusals are *true*, not theatre:

* **Protected corridors** — a curated table of named corridors (Lake Shore,
  King St…) with the bylaw they protect and the intent that breaches it.
* **Real graph data** — each intervention's ``edge_id`` is resolved to its
  actual ``road_name`` / ``road_class`` (Toronto Centreline, already baked into
  the graph), so "this is a designated fire-route arterial" is a checkable fact.

``check_request`` works on text alone (the rehearsed blocked prompt), on
interventions, or on both — passing ``state`` enables the edge → road lookups.
"""

from __future__ import annotations

from dataclasses import dataclass

_CLOSE_OPS = ("close_edge", "remove_edge", "close_node")
_FULL_CLOSURE_WORDS = ("both ways", "both directions", "fully close", "full closure", "close all", "shut down")


@dataclass
class Violation:
    ref: str
    note: str
    severity: str = "block"  # "block" = hard refusal; "warn" = advisory


# Curated protected corridors. ``needs_full_closure`` corridors are only blocked
# on a both-ways/total closure (a single-direction tweak is bylaw-valid); others
# block on any close/remove intent.
PROTECTED_CORRIDORS = [
    {
        "match": ("lake shore", "lakeshore"),
        "needs_full_closure": True,
        "refs": [
            ("Toronto Municipal Code Ch. 880",
             "designated fire route may not be fully closed (emergency access to Stadium South)"),
            ("TTC service bylaw",
             "streetcar-replacement bus lane (509 / 511) must be retained"),
        ],
    },
    {
        "match": ("king street", "king st"),
        "needs_full_closure": False,
        "refs": [
            ("King St Transit Priority Corridor",
             "streetcar priority on 504 King must be preserved; no through-traffic restriction removal"),
        ],
    },
]

# Road classes that are major arterials / controlled-access — closing one is an
# advisory (not an outright block) because it may be a valid event measure.
_MAJOR_CLASSES = {"motorway", "trunk", "primary"}


def _edge_attrs(state) -> dict:
    """{edge_id: {"road_name","road_class","one_way"}} from the live graph."""
    if state is None or not hasattr(state, "graph"):
        return {}
    out: dict = {}
    for _u, _v, d in state.graph.edges(data=True):
        eid = d.get("edge_id") or d.get("id")
        if eid is not None:
            out[eid] = {
                "road_name": (d.get("road_name") or ""),
                "road_class": (d.get("road_class") or ""),
                "one_way": bool(d.get("one_way")),
            }
    return out


def _affected_roads(interventions: list[dict], attrs: dict) -> list[dict]:
    """Resolve close/remove interventions to the real roads they touch."""
    roads = []
    for iv in interventions:
        if iv.get("op") in _CLOSE_OPS:
            meta = attrs.get(iv.get("edge_id"))
            if meta:
                roads.append(meta)
    return roads


def check_request(
    text: str, interventions: list[dict] | None = None, state=None
) -> list[Violation]:
    """Return **hard** (block-severity) constraint violations for the request."""
    t = (text or "").lower()
    interventions = interventions or []
    attrs = _edge_attrs(state)
    affected = _affected_roads(interventions, attrs)
    affected_names = " ".join(r["road_name"].lower() for r in affected)

    text_full_closure = any(w in t for w in _FULL_CLOSURE_WORDS)
    close_intent = "close" in t or "shut" in t or bool(affected)

    violations: list[Violation] = []
    for corridor in PROTECTED_CORRIDORS:
        in_text = any(m in t for m in corridor["match"])
        in_edges = any(m in affected_names for m in corridor["match"])
        if not (in_text or in_edges) or not close_intent:
            continue
        # Full closure = the language says so, OR 2+ of this corridor's edges
        # (i.e. both directions) are being closed/removed.
        corridor_edges = sum(
            1 for r in affected if any(m in r["road_name"].lower() for m in corridor["match"])
        )
        full_closure = text_full_closure or corridor_edges >= 2
        if corridor["needs_full_closure"] and not full_closure:
            continue
        violations.extend(Violation(ref=r, note=n) for r, n in corridor["refs"])
    return violations


def advisories(
    text: str, interventions: list[dict] | None = None, state=None
) -> list[Violation]:
    """Soft, data-derived warnings (not refusals) — e.g. closing a major arterial."""
    interventions = interventions or []
    attrs = _edge_attrs(state)
    out: list[Violation] = []
    for r in _affected_roads(interventions, attrs):
        if r["road_class"] in _MAJOR_CLASSES:
            out.append(
                Violation(
                    ref="Road classification (Centreline)",
                    note=f"{r['road_name'] or 'this segment'} is a {r['road_class']} arterial — "
                    "expect significant diversion; confirm a valid event TMP.",
                    severity="warn",
                )
            )
    return out


def is_blocked(text: str, interventions: list[dict] | None = None, state=None) -> bool:
    return len(check_request(text, interventions, state)) > 0
