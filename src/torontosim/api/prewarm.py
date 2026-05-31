"""Background pre-warming of the recompute cache — the "feels instant" illusion.

The Run button is explicit, but a fresh simulation is ~50s while a cached one is
instant. So whenever the front-end's *pending* parameter state changes it POSTs
``/simulate/prewarm``; we speculatively compute that exact combo plus the
likely-next combos (adjacent hours, the other model) in the background. By the
time the user clicks Run the result is usually already cached.

Stale handling (per the agreed UX):
  * When the pending state changes, prefetch jobs that are *queued but not yet
    started* and no longer wanted are cancelled — so they don't steal compute
    from the new pending state.
  * A job already *in flight* is left to finish (CPU-bound work can't be safely
    interrupted, and one job won't starve a foreground Run on this hardware); it
    just populates the cache in case the user comes back to it.
  * If a Run lands on a combo whose prewarm is in flight, ``recompute_scenario``'s
    per-key lock makes Run ride on that same computation instead of duplicating.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from . import recompute as rc

# Small pool: enough to warm the exact combo + a neighbor concurrently, while
# leaving the box's other cores free for a foreground Run.
_MAX_WORKERS = 2


def _neighbor_combos(model_kind, time_context, interventions, iterations):
    """The pending combo first (highest priority), then likely-next states:
    adjacent hours (wrap 0–23) and the other demand model. Same interventions."""
    tc = dict(time_context or {})
    hour = int(tc.get("hour", 8))
    combos = [(model_kind, tc, interventions, iterations)]  # exact = priority

    for dh in (1, -1):
        combos.append((model_kind, {**tc, "hour": (hour + dh) % 24}, interventions, iterations))

    other = "gnn" if str(model_kind) == "xgboost" else "xgboost"
    combos.append((other, tc, interventions, iterations))
    return combos


class PrewarmManager:
    def __init__(self, state, *, max_workers: int = _MAX_WORKERS):
        self._state = state
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="prewarm")
        self._lock = threading.Lock()
        self._pending: dict[tuple, object] = {}  # cache_key -> Future (not-yet-cached warms)

    def request(self, *, model_kind, time_context, interventions, iterations: int = 4) -> int:
        """Enqueue the pending combo + neighbors; cancel stale queued jobs.

        Returns the number of new background jobs queued.
        """
        combos = _neighbor_combos(model_kind, time_context, interventions, iterations)
        keyed = [(rc.cache_key(m, t, iv), (m, t, iv, it)) for (m, t, iv, it) in combos]
        wanted = {k for k, _ in keyed}

        with self._lock:
            # Cancel queued-but-not-started warms we no longer want.
            for key, fut in list(self._pending.items()):
                if key not in wanted and fut.cancel():  # cancel() fails if running
                    self._pending.pop(key, None)

            queued = 0
            for key, (m, t, iv, it) in keyed:
                if key in self._pending or rc.is_cached(self._state, key):
                    continue
                fut = self._pool.submit(self._warm, m, t, iv, it)
                self._pending[key] = fut
                fut.add_done_callback(lambda f, k=key: self._discard(k))
                queued += 1
            return queued

    def warm_now(
        self, *, model_kind, time_context, interventions=None, iterations: int = 4
    ) -> None:
        """Synchronously warm a single combo (used for the startup default)."""
        self._warm(model_kind, time_context, interventions or [], iterations)

    def _warm(self, model_kind, time_context, interventions, iterations):
        try:
            rc.recompute_scenario(
                self._state,
                model_kind=model_kind,
                time_context=time_context,
                interventions=interventions,
                iterations=iterations,
            )
        except Exception:  # noqa: BLE001 — prewarming is best-effort
            pass

    def _discard(self, key):
        with self._lock:
            self._pending.pop(key, None)
