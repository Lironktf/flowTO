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


def load_default_state(
    graph_path: str | None = None,
    *,
    time_context: dict | None = None,
    max_pairs: int = 800,
) -> AppState:  # pragma: no cover - runtime/server path
    from ..graph.routing import import_graph_json
    from ..model.generate_od_matrix import generate_od_matrix
    from ..model.predict_node_demand import load_demand_model, predict_node_demand

    tc = time_context or {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}
    graph = import_graph_json(graph_path or os.environ.get("TS_GRAPH_JSON", DEFAULT_GRAPH))
    model = load_demand_model()
    demand = predict_node_demand(graph, model, tc)
    od = generate_od_matrix(graph, demand, tc, max_pairs=max_pairs)
    return AppState.from_graph(graph, od, weather=tc.get("weather", "clear"), time_context=tc)
