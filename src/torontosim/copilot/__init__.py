"""Planner copilot (P09): NL → validated tool calls, preview-first, cited.

Local Nemotron (via Ollama on the Spark) turns plain English into a validated,
schema-constrained scenario tool call — read-only by default, preview-before-
apply, never mutating the sim directly. A deterministic demo router handles the
two rehearsed prompts so the stage demo never depends on live decoding; the
live Nemotron path is Spark-gated. RAG cites a small curated bylaw corpus.
"""

from __future__ import annotations

from .planner import plan_intervention

__all__ = ["plan_intervention"]
