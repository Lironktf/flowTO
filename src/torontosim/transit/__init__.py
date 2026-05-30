"""Transit overlay (P08): GTFS → route lines + scheduled vehicle trajectories.

A **visual overlay decoupled from the traffic math** (no rider mode-choice yet —
that's stretch S1). The server precomputes per-trip ``{path, timestamps}`` in
seconds-since-midnight (float32-safe for deck.gl TripsLayer); the frontend
animates them synced to the time scrubber.
"""

from __future__ import annotations

__all__ = ["routes", "trajectories"]
