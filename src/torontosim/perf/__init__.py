"""Performance instrumentation (P11): timing harness + benchmark CLI.

Turns performance claims into measured evidence. The headline comparison is
**full-city recompute vs blast-radius recompute** latency. Counters are
near-zero overhead and deterministic in label; Nsight captures (Spark) add the
GPU timeline evidence.
"""

from __future__ import annotations

from .timing import get_timings, reset_timings, timed, timer

__all__ = ["timed", "timer", "get_timings", "reset_timings"]
