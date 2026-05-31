"""Production state bootstrap: load the full Toronto graph + baseline OD (P06).

Used by ``api.app.serve``. Builds the demand → OD once at startup so the server
shares a single read-only baseline graph. Kept out of the test path (tests
inject a small graph via ``AppState.from_graph``).
"""

from __future__ import annotations

import os

from .store import AppState

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_GRAPH = os.path.join(_REPO_ROOT, "data", "graph", "toronto_drive_graph.json")
DEFAULT_PARQUET = os.path.join(_REPO_ROOT, "data", "parquet")


def resolve_graph_source(
    source: str | None = None, *, env: dict | None = None, parquet_dir: str | None = None
) -> str:
    """Pick the graph backend.

    Precedence: explicit ``source`` arg > ``TS_GRAPH_SOURCE`` env > **auto**.
    Auto prefers the real **Centreline** graph when its baked parquet store is
    present (the fidelity default on a baked host like the Spark), else falls back
    to the baseline-safe **OSMnx** JSON (always committed — so CI, fresh clones,
    and local dev without a parquet store keep booting).
    """
    env = os.environ if env is None else env
    chosen = (source or env.get("TS_GRAPH_SOURCE") or "").strip().lower()
    if chosen:
        return "centreline" if chosen == "centreline" else "osmnx"
    pq = parquet_dir or env.get("TS_PARQUET_DIR", DEFAULT_PARQUET)
    has_centreline = bool(pq) and os.path.exists(os.path.join(pq, "centreline.parquet"))
    return "centreline" if has_centreline else "osmnx"


def load_graph(
    graph_source: str | None = None,
    *,
    graph_path: str | None = None,
    parquet_dir: str | None = None,
    env: dict | None = None,
):
    """Load the baseline graph for the chosen source (default OSMnx JSON).

    ``centreline`` builds from the P01-baked parquet store and calibrates
    capacity against the real TMC parquet; ``osmnx`` imports Liron's committed
    graph JSON. Never deletes the OSMnx fallback.
    """
    from ..graph.routing import import_graph_json

    source = resolve_graph_source(graph_source, env=env, parquet_dir=parquet_dir)
    if source == "centreline":
        from ..graph import calibrate_capacity
        from ..graph.centreline_loader import load_from_parquet

        pq_dir = parquet_dir or (os.environ if env is None else env).get(
            "TS_PARQUET_DIR", DEFAULT_PARQUET
        )
        graph = load_from_parquet(pq_dir)
        tmc_path = os.path.join(pq_dir, "tmc.parquet")
        if os.path.exists(tmc_path):
            import pyarrow.parquet as pq

            calibrate_capacity.calibrate(graph, pq.read_table(tmc_path).to_pylist())
        return graph
    return import_graph_json(graph_path or os.environ.get("TS_GRAPH_JSON", DEFAULT_GRAPH))


def load_default_state(
    graph_path: str | None = None,
    *,
    time_context: dict | None = None,
    max_pairs: int = 800,
    graph_source: str | None = None,
) -> AppState:  # pragma: no cover - runtime/server path
    """Fast boot: load the graph only.

    The demand model (~27 MB) + baseline OD are NOT built here — they're produced
    lazily on first *legacy* use via ``AppState.ensure_od`` (scenario run/preview/
    compare and ``/demo/run``). The main UX (measured/ML baseline + the ML
    day-stream) never needs ``state.od_matrix``: ``api/recompute.py`` grounds its
    own OD per request. So the server starts serving ``/edges`` and ``/day/stream``
    immediately instead of blocking startup on a model load + 27k-node prediction.
    """
    tc = time_context or {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}
    graph = load_graph(graph_source, graph_path=graph_path)
    state = AppState.from_graph(graph, [], weather=tc.get("weather", "clear"), time_context=tc)
    state.od_max_pairs = max_pairs
    return state
