from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch
from torch.nn import SmoothL1Loss

from .build_gnn_dataset import build_dataset
from .model import PYG_AVAILABLE, build_model
from .utils import (
    DEFAULT_DATASET_PATH,
    DEFAULT_GRAPH_PATH,
    DEFAULT_METRICS_PATH,
    DEFAULT_MODEL_PATH,
    classification_accuracy,
    device_report,
    mae,
    rmse,
    r2_score,
    seed_everything,
    torch_device,
    write_json,
)


def _load_dataset(path: Path, graph_path: Path, rebuild: bool, max_label_rows: int | None) -> dict:
    if rebuild or not path.exists():
        return build_dataset(graph_path=graph_path, output=path, max_label_rows=max_label_rows)
    return torch.load(path, map_location="cpu", weights_only=False)


def _slice_batch(dataset: dict, mask: torch.Tensor, batch_size: int, device: torch.device):
    idx = torch.nonzero(mask, as_tuple=False).flatten()
    order = idx[torch.randperm(len(idx))]
    for start in range(0, len(order), batch_size):
        sample_ids = order[start : start + batch_size]
        edge_sample_idx = dataset["sample_edge_idx"][sample_ids].to(device)
        context = dataset["context_attr"][sample_ids].to(device)
        target = dataset["y"][sample_ids].to(device)
        yield edge_sample_idx, context, target


@torch.no_grad()
def _evaluate(model, dataset: dict, mask: torch.Tensor, device: torch.device, batch_size: int) -> dict:
    model.eval()
    preds = []
    targets = []
    for edge_sample_idx, context, target in _slice_batch(dataset, mask, batch_size, device):
        pred = model(
            dataset["x"].to(device),
            dataset["edge_index"].to(device),
            dataset["edge_attr"].to(device),
            context,
            edge_sample_idx,
        )
        preds.append(pred.detach().cpu())
        targets.append(target.detach().cpu())
    pred_t = torch.cat(preds) if preds else torch.empty(0)
    target_t = torch.cat(targets) if targets else torch.empty(0)
    if len(pred_t) == 0:
        return {"mae": None, "rmse": None, "r2": None, "risk_accuracy": None}
    return {
        "mae": mae(pred_t, target_t),
        "rmse": rmse(pred_t, target_t),
        "r2": r2_score(pred_t, target_t),
        "risk_accuracy": classification_accuracy(pred_t, target_t),
    }


def train(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    graph_path: Path = DEFAULT_GRAPH_PATH,
    model_path: Path = DEFAULT_MODEL_PATH,
    metrics_path: Path = DEFAULT_METRICS_PATH,
    epochs: int = 50,
    batch_size: int = 8192,
    hidden_dim: int = 128,
    num_layers: int = 2,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    dropout: float = 0.15,
    seed: int = 42,
    rebuild_dataset: bool = False,
    max_label_rows: int | None = None,
    prefer_cuda: bool = True,
    backend: str = "auto",
) -> dict:
    seed_everything(seed)
    dataset = _load_dataset(dataset_path, graph_path, rebuild_dataset, max_label_rows)
    device = torch_device(prefer_cuda=prefer_cuda)
    report = device_report(device)
    print(f"device: {report}")

    if backend == "auto":
        backend = "graphsage" if PYG_AVAILABLE else "mlp"
    if backend == "graphsage" and not PYG_AVAILABLE:
        print("torch_geometric is unavailable; using graph-feature MLP fallback")
        backend = "mlp"

    model = build_model(
        backend=backend,
        node_in_dim=dataset["x"].shape[1],
        edge_in_dim=dataset["edge_attr"].shape[1],
        context_in_dim=dataset["context_attr"].shape[1],
        hidden_dim=hidden_dim,
        num_layers=num_layers,
        dropout=dropout,
    ).to(device)

    x = dataset["x"].to(device)
    edge_index = dataset["edge_index"].to(device)
    edge_attr = dataset["edge_attr"].to(device)
    train_mask = dataset["train_mask"]
    val_mask = dataset["val_mask"]

    loss_fn = SmoothL1Loss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    best_val = float("inf")
    best_state = None
    history = []
    start_time = time.perf_counter()

    for epoch in range(1, epochs + 1):
        model.train()
        losses = []
        for edge_sample_idx, context, target in _slice_batch(dataset, train_mask, batch_size, device):
            optimizer.zero_grad(set_to_none=True)
            pred = model(x, edge_index, edge_attr, context, edge_sample_idx)
            loss = loss_fn(pred, target)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))

        train_metrics = _evaluate(model, dataset, train_mask, device, batch_size)
        val_metrics = _evaluate(model, dataset, val_mask, device, batch_size)
        row = {
            "epoch": epoch,
            "loss": sum(losses) / max(len(losses), 1),
            "train_mae": train_metrics["mae"],
            "val_mae": val_metrics["mae"],
            "val_rmse": val_metrics["rmse"],
            "val_r2": val_metrics["r2"],
            "val_risk_accuracy": val_metrics["risk_accuracy"],
        }
        history.append(row)
        print(
            f"epoch={epoch:03d} loss={row['loss']:.4f} "
            f"train_mae={row['train_mae']:.4f} val_mae={row['val_mae']:.4f}"
        )
        score = val_metrics["mae"] if val_metrics["mae"] is not None else train_metrics["mae"]
        if score is not None and score < best_val:
            best_val = score
            best_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "model_state_dict": model.state_dict(),
        "backend": backend,
        "model_name": "GraphSAGE edge predictor" if backend == "graphsage" else "Graph-feature edge MLP fallback",
        "node_in_dim": dataset["x"].shape[1],
        "edge_in_dim": dataset["edge_attr"].shape[1],
        "context_in_dim": dataset["context_attr"].shape[1],
        "hidden_dim": hidden_dim,
        "num_layers": num_layers,
        "dropout": dropout,
        "node_standardizer": dataset["node_standardizer"],
        "edge_standardizer": dataset["edge_standardizer"],
        "context_standardizer": dataset["context_standardizer"],
        "feature_names": {
            "node": dataset["node_feature_names"],
            "edge": dataset["edge_feature_names"],
            "context": dataset["context_feature_names"],
        },
        "label_source": dataset.get("label_source", {}),
    }
    torch.save(checkpoint, model_path)

    final_train = _evaluate(model, dataset, train_mask, device, batch_size)
    final_val = _evaluate(model, dataset, val_mask, device, batch_size)
    metrics = {
        **report,
        "backend": backend,
        "model_path": str(model_path),
        "dataset_path": str(dataset_path),
        "epochs": epochs,
        "batch_size": batch_size,
        "hidden_dim": hidden_dim,
        "num_layers": num_layers,
        "dropout": dropout,
        "lr": lr,
        "weight_decay": weight_decay,
        "elapsed_seconds": round(time.perf_counter() - start_time, 3),
        "samples": int(len(dataset["y"])),
        "train_samples": int(train_mask.sum()),
        "val_samples": int(val_mask.sum()),
        "train": final_train,
        "val": final_val,
        "history": history,
    }
    write_json(metrics_path, metrics)
    print(f"saved model {model_path}")
    print(f"saved metrics {metrics_path}")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train FlowTO GNN edge-congestion model.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--metrics-out", type=Path, default=DEFAULT_METRICS_PATH)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=8192)
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--dropout", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rebuild-dataset", action="store_true")
    parser.add_argument("--max-label-rows", type=int, default=None)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--backend", choices=["auto", "graphsage", "mlp"], default="auto")
    args = parser.parse_args()
    train(
        dataset_path=args.dataset,
        graph_path=args.graph,
        model_path=args.model_out,
        metrics_path=args.metrics_out,
        epochs=args.epochs,
        batch_size=args.batch_size,
        hidden_dim=args.hidden_dim,
        num_layers=args.num_layers,
        lr=args.lr,
        weight_decay=args.weight_decay,
        dropout=args.dropout,
        seed=args.seed,
        rebuild_dataset=args.rebuild_dataset,
        max_label_rows=args.max_label_rows,
        prefer_cuda=not args.cpu,
        backend=args.backend,
    )


if __name__ == "__main__":
    main()

