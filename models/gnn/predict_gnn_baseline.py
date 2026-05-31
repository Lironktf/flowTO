from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path

import torch

from .build_gnn_dataset import build_dataset
from .model import build_model
from .utils import (
    DEFAULT_DATASET_PATH,
    DEFAULT_GRAPH_PATH,
    DEFAULT_MODEL_PATH,
    DEFAULT_PREDICTIONS_PATH,
    apply_standardizer,
    context_vector,
    pressure_time_multiplier,
    pressure_to_risk,
    torch_device,
    write_json,
)


def _load_or_build_dataset(dataset_path: Path, graph_path: Path) -> dict:
    if dataset_path.exists():
        return torch.load(dataset_path, map_location="cpu", weights_only=False)
    return build_dataset(graph_path=graph_path, output=dataset_path)


def load_checkpoint_model(model_path: Path, device: torch.device):
    checkpoint = torch.load(model_path, map_location=device, weights_only=False)
    model = build_model(
        backend=checkpoint["backend"],
        node_in_dim=checkpoint["node_in_dim"],
        edge_in_dim=checkpoint["edge_in_dim"],
        context_in_dim=checkpoint["context_in_dim"],
        hidden_dim=checkpoint["hidden_dim"],
        num_layers=checkpoint.get("num_layers", 2),
        dropout=checkpoint.get("dropout", 0.0),
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()
    return model, checkpoint


@lru_cache(maxsize=4)
@torch.no_grad()
def _prepare_inference(
    model_path: str,
    dataset_path: str,
    graph_path: str,
    device_str: str,
):
    """Load + device-resident dataset/model, with node embeddings precomputed.

    Cached so repeated baseline predictions (every time-context / scenario in the
    live twin) reuse the on-device tensors instead of re-reading the dataset and
    checkpoint from disk and re-uploading to the GPU each call. The node
    embeddings ``h`` depend only on the graph + node features (not the time
    context) and dropout is off in eval mode, so they are encoded once here and
    reused across every prediction. Pass distinct paths to invalidate.
    """
    device = torch.device(device_str)
    dataset = _load_or_build_dataset(Path(dataset_path), Path(graph_path))
    model, checkpoint = load_checkpoint_model(Path(model_path), device)
    x = dataset["x"].to(device)
    edge_index = dataset["edge_index"].to(device)
    edge_attr = dataset["edge_attr"].to(device)
    h = model.encode_nodes(x, edge_index)  # context-independent — encode once
    return dataset, model, checkpoint, edge_index, edge_attr, h, device


@torch.no_grad()
def predict_baseline_edges(
    model_path: Path = DEFAULT_MODEL_PATH,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    graph_path: Path = DEFAULT_GRAPH_PATH,
    time_context: dict | None = None,
    output_path: Path | None = DEFAULT_PREDICTIONS_PATH,
    batch_size: int = 20000,
    prefer_cuda: bool = True,
) -> dict:
    device = torch_device(prefer_cuda=prefer_cuda)
    dataset, model, checkpoint, edge_index, edge_attr, h, device = _prepare_inference(
        str(model_path), str(dataset_path), str(graph_path), str(device)
    )

    raw_ctx = torch.tensor([context_vector(time_context)], dtype=torch.float32)
    ctx = apply_standardizer(raw_ctx, checkpoint["context_standardizer"]).to(device)

    preds: list[torch.Tensor] = []
    num_edges = edge_attr.shape[0]
    for start in range(0, num_edges, batch_size):
        end = min(start + batch_size, num_edges)
        edge_sample_idx = torch.arange(start, end, dtype=torch.long, device=device)
        batch_ctx = ctx.expand(end - start, -1)
        # Reuse the once-encoded node embeddings; only the small edge head runs
        # per batch (previously every batch re-ran full graph message passing).
        pred = model.score_edges(h, edge_index, edge_attr, batch_ctx, edge_sample_idx)
        preds.append(pred.detach().cpu())
    pressures = torch.cat(preds).numpy()

    edges = []
    for idx, pressure in enumerate(pressures):
        meta = dataset["edge_meta"][idx]
        pressure_f = max(float(pressure), 0.0)
        capacity = float(meta["capacity"])
        base_time = float(meta["base_time_min"])
        predicted_load = pressure_f * capacity
        predicted_time = base_time * pressure_time_multiplier(pressure_f)
        edges.append(
            {
                "edge_id": meta["edge_id"],
                "from_node": meta["from_node"],
                "to_node": meta["to_node"],
                "road_name": meta.get("road_name"),
                "road_class": meta.get("road_class"),
                "predicted_pressure": round(pressure_f, 4),
                "predicted_load": round(predicted_load, 2),
                "capacity": round(capacity, 2),
                "base_time_min": round(base_time, 4),
                "predicted_time_min": round(predicted_time, 4),
                "risk": pressure_to_risk(pressure_f),
            }
        )

    payload = {
        "time_context": time_context or {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"},
        "model": checkpoint.get("model_name", "GraphSAGE edge predictor"),
        "backend": checkpoint.get("backend"),
        "edges": edges,
    }
    if output_path:
        write_json(output_path, payload)
        print(f"saved predictions {output_path} edges={len(edges)}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Export GNN baseline predictions for every road edge.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_PREDICTIONS_PATH)
    parser.add_argument("--hour", type=int, default=17)
    parser.add_argument("--day-of-week", type=int, default=4)
    parser.add_argument("--month", type=int, default=6)
    parser.add_argument("--weather", default="clear")
    parser.add_argument("--temperature-c", type=float, default=18.0)
    parser.add_argument("--precipitation-mm", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=20000)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    predict_baseline_edges(
        model_path=args.model,
        dataset_path=args.dataset,
        graph_path=args.graph,
        output_path=args.output,
        batch_size=args.batch_size,
        prefer_cuda=not args.cpu,
        time_context={
            "hour": args.hour,
            "day_of_week": args.day_of_week,
            "month": args.month,
            "weather": args.weather,
            "temperature_c": args.temperature_c,
            "precipitation_mm": args.precipitation_mm,
        },
    )


if __name__ == "__main__":
    main()

