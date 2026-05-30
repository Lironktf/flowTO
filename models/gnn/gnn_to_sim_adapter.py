from __future__ import annotations

from pathlib import Path

from .predict_gnn_baseline import predict_baseline_edges
from .utils import DEFAULT_DATASET_PATH, DEFAULT_GRAPH_PATH, DEFAULT_MODEL_PATH


def predict_gnn_edge_state(
    graph=None,
    time_context: dict | None = None,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    graph_path: str | Path = DEFAULT_GRAPH_PATH,
) -> dict[str, dict]:
    """Return {edge_id: state} for simulator/router baseline initialization.

    ``graph`` is accepted for the simulator-facing API. The current tensor
    dataset is built from ``graph_path`` so inference can run without mutating
    the live NetworkX graph.
    """
    payload = predict_baseline_edges(
        model_path=Path(model_path),
        dataset_path=Path(dataset_path),
        graph_path=Path(graph_path),
        time_context=time_context,
        output_path=None,
    )
    return {
        item["edge_id"]: {
            "predicted_load": item["predicted_load"],
            "predicted_pressure": item["predicted_pressure"],
            "predicted_time_min": item["predicted_time_min"],
            "risk": item["risk"],
        }
        for item in payload["edges"]
    }


def apply_gnn_baseline_to_graph(graph, edge_state: dict[str, dict] | None = None, **predict_kwargs):
    """Mutate a NetworkX road graph with GNN load/pressure/current_time_min values."""
    if edge_state is None:
        edge_state = predict_gnn_edge_state(graph=graph, **predict_kwargs)
    for _u, _v, data in graph.edges(data=True):
        state = edge_state.get(str(data.get("edge_id")))
        if not state:
            continue
        data["load"] = state["predicted_load"]
        data["pressure"] = state["predicted_pressure"]
        data["current_time_min"] = state["predicted_time_min"]
        data["risk"] = state["risk"]
    return graph


def gnn_state_as_xgboost_shape(edge_state: dict[str, dict]) -> dict[str, dict]:
    """Compatibility adapter for call sites that expect baseline prediction fields."""
    return {
        edge_id: {
            "load": state["predicted_load"],
            "pressure": state["predicted_pressure"],
            "current_time_min": state["predicted_time_min"],
            "risk": state["risk"],
        }
        for edge_id, state in edge_state.items()
    }

