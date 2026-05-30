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


def resolve_graph_source(source: str | None, *, env: dict | None = None) -> str:
    """Pick the graph backend. Defaults to OSMnx (baseline-safe); Centreline opt-in.

    Precedence: explicit ``source`` arg > ``TS_GRAPH_SOURCE`` env > ``osmnx``.
    """
    env = os.environ if env is None else env
    chosen = (source or env.get("TS_GRAPH_SOURCE") or "osmnx").strip().lower()
    return "centreline" if chosen == "centreline" else "osmnx"


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

    source = resolve_graph_source(graph_source, env=env)
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
    from ..model.generate_od_matrix import generate_od_matrix
    from ..model.predict_node_demand import load_demand_model, predict_node_demand

    tc = time_context or {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}
    graph = load_graph(graph_source, graph_path=graph_path)
    model = load_demand_model()
    demand = predict_node_demand(graph, model, tc)
    od = generate_od_matrix(graph, demand, tc, max_pairs=max_pairs)
    return AppState.from_graph(graph, od, weather=tc.get("weather", "clear"), time_context=tc)
