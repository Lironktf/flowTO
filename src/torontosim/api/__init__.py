"""TorontoSim backend API (P06).

A single FastAPI process exposing the simulation to the frontend: REST for
scenario CRUD + runs + compare (+ copilot/optimizer hooks), and a WebSocket that
streams compact binary edge tick frames. In-memory scenario state, no DB.

``create_app(state=...)`` is a factory so tests can inject a small graph instead
of loading the full Toronto graph.
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
