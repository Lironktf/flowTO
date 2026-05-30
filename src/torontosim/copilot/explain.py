"""Plain-language result explanation (P09).

Summarizes a ``CompareResult``-shaped diff grounded in the run's actual numbers
(no fabrication) plus optional RAG citations. Free-text — no schema constraint.
A deterministic template is the demo-safe path; a live model can elaborate.
"""

from __future__ import annotations


def explain_compare(summary_delta: dict, *, top_edges: list | None = None) -> str:
    """Turn summary deltas into a one-paragraph planner-readable summary."""
    parts: list[str] = []
    delay = summary_delta.get("average_pressure")
    if isinstance(delay, (int, float)):
        direction = "eased" if delay < 0 else "worsened"
        parts.append(f"Average network pressure {direction} by {abs(delay):.3f}.")
    for key, label in (
        ("high_risk_edges", "high-risk edges"),
        ("severe_edges", "severe edges"),
    ):
        v = summary_delta.get(key)
        if isinstance(v, (int, float)) and v != 0:
            parts.append(f"{'+' if v > 0 else ''}{int(v)} {label}.")
    if top_edges:
        names = [e.get("road_name") or e.get("edge_id") for e in top_edges[:3]]
        parts.append("Most affected: " + ", ".join(str(n) for n in names) + ".")
    if not parts:
        return "No material change in the network metrics."
    return " ".join(parts)
