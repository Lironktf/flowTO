"""SSOT closure-assessment (P09) — warn, don't block.

One module both the copilot and manual (clickops) closures call. It NEVER
refuses: it returns severity-coded ``Warning``s the user can override. The
deterministic floor comes from ``constraints.py`` (curated protected corridors +
real graph road-class) so every warning carries a real bylaw ref; an optional
RAG pass attaches the most relevant baked Municipal Code section as added
grounding. Replaces the old hard ``check_request`` refusal in the planner.

``assess(interventions, state)`` works on interventions alone (clickops) or with
the originating prompt text (copilot) — passing ``state`` enables edge→road lookups.
"""

from __future__ import annotations

from .constraints import advisories, check_request
from .tools import Warning


def _to_op(iv) -> dict:
    return iv if isinstance(iv, dict) else iv.to_op()


def _rag_context(ops: list[dict], state) -> list[Warning]:
    """Best-effort: retrieve the most relevant baked bylaw section for the affected
    roads and attach it as an info-level citation. Never raises (corpus optional)."""
    closing = [o for o in ops if o.get("op") in ("close_edge", "remove_edge", "close_node")]
    if not closing:
        return []
    try:
        from . import rag

        # Build a query from the affected road names (fall back to a generic one).
        names = []
        attrs = {}
        if state is not None and hasattr(state, "graph"):
            for _u, _v, d in state.graph.edges(data=True):
                eid = d.get("edge_id") or d.get("id")
                if eid:
                    attrs[eid] = d.get("road_name") or ""
        names = [attrs.get(o.get("edge_id"), "") for o in closing]
        query = "road closure permit conditions " + " ".join(n for n in names if n)
        hits = rag.retrieve(query, k=1)
    except Exception:  # noqa: BLE001 — RAG is enrichment, never a hard dependency
        return []
    if not hits:
        return []
    h = hits[0]
    return [
        Warning(
            severity="info",
            title="Relevant bylaw",
            detail=h.get("title") or "See the Municipal Code for closure conditions.",
            ref=(h.get("source") or "").split(".")[0] or None,
        )
    ]


def assess(interventions, state, *, prompt: str = "", with_rag: bool = True) -> list[Warning]:
    """Severity-coded warnings for a proposed change — never a refusal.

    Deterministic floor: protected-corridor / bylaw conflicts → ``danger``;
    major-arterial / data-derived advisories → ``warn``. Optional RAG context →
    ``info``. Deduped. Empty list = nothing of concern.
    """
    ops = [_to_op(iv) for iv in (interventions or [])]
    out: list[Warning] = []
    seen: set = set()

    def add(severity: str, title: str, detail: str, ref):
        key = (severity, ref, detail)
        if key in seen:
            return
        seen.add(key)
        out.append(Warning(severity=severity, title=title, detail=detail, ref=ref))

    # Hard-constraint conflicts are now DANGER warnings (override-able), not blocks.
    for v in check_request(prompt, ops, state):
        add("danger", "Bylaw conflict", v.note, v.ref)
    # Soft, data-derived advisories (e.g. closing a major arterial).
    for v in advisories(prompt, ops, state):
        add("warn", "Advisory", v.note, v.ref)
    if with_rag:
        for w in _rag_context(ops, state):
            add(w.severity, w.title, w.detail, w.ref)
    return out
