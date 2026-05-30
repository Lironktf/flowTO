"""Deterministic constraint checker (P09) — hard bylaw guardrails.

Runs BEFORE anything reaches the sim: a request that breaches a hard constraint
is refused with citations, the network unchanged. This is the "constraint-
blocked" demo state and the safety floor under the copilot.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Violation:
    ref: str
    note: str


# Hard constraints keyed to corridors/roads they protect.
def check_request(text: str, interventions: list[dict] | None = None) -> list[Violation]:
    """Return hard-constraint violations for an NL request + intervention set."""
    t = (text or "").lower()
    interventions = interventions or []
    violations: list[Violation] = []

    mentions_lakeshore = "lake shore" in t or "lakeshore" in t
    both_ways = "both ways" in t or "both directions" in t or "fully close" in t or "close all" in t
    close_intent = "close" in t or any(
        iv.get("op") in ("close_edge", "remove_edge") for iv in interventions
    )

    # Fully closing Lake Shore Blvd W removes the only emergency corridor +
    # the 509/511 replacement-bus lane.
    if mentions_lakeshore and close_intent and both_ways:
        violations.append(
            Violation(
                ref="Toronto Municipal Code Ch. 880",
                note="designated fire route may not be fully closed (emergency access to Stadium South)",
            )
        )
        violations.append(
            Violation(
                ref="TTC service bylaw",
                note="streetcar-replacement bus lane (509 / 511) must be retained",
            )
        )
    return violations


def is_blocked(text: str, interventions: list[dict] | None = None) -> bool:
    return len(check_request(text, interventions)) > 0
