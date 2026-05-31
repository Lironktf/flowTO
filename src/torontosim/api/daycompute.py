"""Compute a whole day as a 24-hour time series — the engine behind free playback.

A **view** is everything that defines a simulation *except the hour*:
``(demand_model, day_of_week, month, interventions)``. The front-end shows
congestion *over time for a day*, so scrubbing/▶play must be free playback of an
already-computed day — never a recompute. This module fills a view's 24 hourly
frames speculatively: the moment a view is defined (page load, or any change to
model / day-of-week / month / edits) we start computing the **current hour first**
(so the visible map paints ASAP) then the rest in the background.

Each hour is just a per-hour ``recompute_scenario`` call (api/recompute.py) — so
the LRU cache, the per-key dedup lock, and ``model_actual`` all come for free; an
hour already in the cache returns instantly. ``simulate_scenario`` copies the
graph internally, so the hours run **concurrently** on a bounded, BLAS-pinned
pool without corrupting the shared ``state.graph`` (see scripts/run_api.sh for the
1-thread-per-worker pinning that keeps N parallel sims from oversubscribing).

The WS endpoint (``/day/stream`` in app.py) drives this pool and streams each
hour's binary frame as it completes (current hour first). Superseding a view =
the client closing its socket and opening a new one; queued-but-not-started hours
are cancelled, in-flight ones finish into the cache (harmless, may help on return).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import recompute as rc

# 24 hourly equilibrium sims per day, each ~1 core (BLAS pinned). The box has 20
# cores; 16 workers fill a full day in ~2 waves while leaving headroom for
# uvicorn + the foreground request path.
DAY_POOL_WORKERS = 16

HOURS_PER_DAY = 24


def hour_order(current_hour: int) -> list:
    """Hours 0..23 ordered so the visible neighbourhood fills first:
    ``current, current±1, current±2, …`` (wrapping the clock)."""
    h = int(current_hour) % HOURS_PER_DAY
    order = [h]
    for d in range(1, HOURS_PER_DAY):
        for cand in ((h + d) % HOURS_PER_DAY, (h - d) % HOURS_PER_DAY):
            if cand not in order:
                order.append(cand)
        if len(order) >= HOURS_PER_DAY:
            break
    return order[:HOURS_PER_DAY]


def base_time_context(time_context: dict | None) -> dict:
    """Project the per-request ``time_context`` down to a *view* tc: drop ``hour``
    (it's the playback axis now) and force ``weather="clear"`` (product rule)."""
    tc = dict(time_context or {})
    tc.pop("hour", None)
    tc["weather"] = "clear"
    return tc


class DayCompute:
    def __init__(self, state, *, max_workers: int = DAY_POOL_WORKERS):
        self._state = state
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="daycompute")

    def is_hour_cached(self, model_kind, base_tc, interventions, hour) -> bool:
        key = rc.cache_key(model_kind, {**base_tc, "hour": int(hour)}, interventions)
        return rc.is_cached(self._state, key)

    def compute_hour(self, model_kind, base_tc, interventions, hour, iterations: int = 4):
        """Run (or fetch cached) one hour. Returns ``(hour, result)`` where result
        is ``recompute_scenario``'s dict ({records, summary, rgap, model_actual,
        cached}). Runs on a pool thread."""
        res = rc.recompute_scenario(
            self._state,
            model_kind=model_kind,
            time_context={**base_tc, "hour": int(hour)},
            interventions=interventions,
            iterations=iterations,
        )
        return int(hour), res

    def warm_day(
        self, *, model_kind, base_tc, interventions=None, current_hour: int = 8, iterations: int = 4
    ) -> int:
        """Fire-and-forget: submit all 24 hours of a view to the pool (current hour
        first). Used for the startup default-view warm. Non-blocking; returns the
        number of hours submitted (skips already-cached ones)."""
        interventions = list(interventions or [])
        submitted = 0
        for hour in hour_order(current_hour):
            if self.is_hour_cached(model_kind, base_tc, interventions, hour):
                continue
            self.pool.submit(
                self.compute_hour, model_kind, base_tc, interventions, hour, iterations
            )
            submitted += 1
        return submitted
