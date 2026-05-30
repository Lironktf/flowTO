from __future__ import annotations

import argparse
from pathlib import Path

import networkx as nx
import pandas as pd
import torch

from .utils import (
    CONTEXT_FEATURE_NAMES,
    DEFAULT_DATASET_PATH,
    DEFAULT_GRAPH_PATH,
    DEFAULT_TRAIN_LABELS,
    DEFAULT_VAL_LABELS,
    DOWNTOWN_LAT,
    DOWNTOWN_LON,
    EDGE_FEATURE_NAMES,
    NODE_FEATURE_NAMES,
    bearing_features,
    context_vector,
    fit_standardizer,
    haversine_km,
    load_road_graph,
    road_class_one_hot,
    road_class_rank,
    safe_float,
)


def _pagerank(graph: nx.MultiDiGraph, enabled: bool) -> dict[object, float]:
    if not enabled:
        return {node: 0.0 for node in graph.nodes}
    try:
        import cudf
        import cugraph

        rows = [(u, v, safe_float(data.get("capacity"), 1.0)) for u, v, data in graph.edges(data=True)]
        if rows:
            gdf = cudf.DataFrame(rows, columns=["src", "dst", "capacity"])
            cg = cugraph.Graph(directed=True)
            cg.from_cudf_edgelist(gdf, source="src", destination="dst", edge_attr="capacity")
            ranks = cugraph.pagerank(cg, max_iter=100, tol=1e-5).to_pandas()
            return dict(zip(ranks["vertex"].tolist(), ranks["pagerank"].astype(float).tolist()))
    except Exception:
        pass
    try:
        return nx.pagerank(graph, weight="capacity", max_iter=100, tol=1e-5)
    except Exception:
        return {node: 0.0 for node in graph.nodes}


def _build_static_tensors(graph: nx.MultiDiGraph, use_pagerank: bool) -> dict:
    nodes = list(graph.nodes())
    node_to_idx = {node: idx for idx, node in enumerate(nodes)}
    pr = _pagerank(graph, use_pagerank)

    x_rows: list[list[float]] = []
    for node in nodes:
        data = graph.nodes[node]
        lat = safe_float(data.get("lat", data.get("y")))
        lon = safe_float(data.get("lon", data.get("x")))
        x_rows.append(
            [
                lat,
                lon,
                safe_float(data.get("degree"), graph.degree(node)),
                float(graph.in_degree(node)),
                float(graph.out_degree(node)),
                haversine_km(lat, lon, DOWNTOWN_LAT, DOWNTOWN_LON),
                float(pr.get(node, 0.0)),
            ]
        )

    edge_index_rows: list[list[int]] = [[], []]
    edge_attr_rows: list[list[float]] = []
    edge_meta: list[dict] = []
    edge_id_to_idx: dict[str, int] = {}

    for edge_idx, (u, v, _k, data) in enumerate(graph.edges(keys=True, data=True)):
        edge_id = str(data.get("edge_id") or f"{u}-{v}-{_k}")
        edge_id_to_idx[edge_id] = edge_idx
        edge_index_rows[0].append(node_to_idx[u])
        edge_index_rows[1].append(node_to_idx[v])

        udata = graph.nodes[u]
        vdata = graph.nodes[v]
        bsin, bcos = bearing_features(udata, vdata)
        rc = data.get("road_class")
        edge_attr_rows.append(
            [
                safe_float(data.get("length_m")),
                float(road_class_rank(rc)),
                safe_float(data.get("lanes"), 1.0),
                safe_float(data.get("speed_kmh"), 40.0),
                safe_float(data.get("capacity"), 1.0),
                safe_float(data.get("base_time_min"), 0.0),
                float(bool(data.get("one_way"))),
                bsin,
                bcos,
                float(graph.degree(u)),
                float(graph.degree(v)),
                *road_class_one_hot(rc),
            ]
        )
        edge_meta.append(
            {
                "edge_id": edge_id,
                "from_node": u,
                "to_node": v,
                "road_name": data.get("road_name"),
                "road_class": rc,
                "capacity": safe_float(data.get("capacity"), 1.0),
                "base_time_min": safe_float(data.get("base_time_min"), 0.0),
                "length_m": safe_float(data.get("length_m"), 0.0),
                "speed_kmh": safe_float(data.get("speed_kmh"), 0.0),
                "lanes": safe_float(data.get("lanes"), 0.0),
                "status": data.get("status", "open"),
            }
        )

    return {
        "node_ids": nodes,
        "node_to_idx": node_to_idx,
        "edge_id_to_idx": edge_id_to_idx,
        "edge_meta": edge_meta,
        "x_raw": torch.tensor(x_rows, dtype=torch.float32),
        "edge_index": torch.tensor(edge_index_rows, dtype=torch.long),
        "edge_attr_raw": torch.tensor(edge_attr_rows, dtype=torch.float32),
    }


def _candidate_edge_indices(graph: nx.MultiDiGraph, node, strategy: str, edge_id_to_idx: dict[str, int]) -> list[int]:
    candidates = []
    if strategy in ("outgoing", "incident"):
        for _u, _v, _k, data in graph.out_edges(node, keys=True, data=True):
            idx = edge_id_to_idx.get(str(data.get("edge_id")))
            if idx is not None:
                candidates.append(idx)
    if strategy in ("incoming", "incident"):
        for _u, _v, _k, data in graph.in_edges(node, keys=True, data=True):
            idx = edge_id_to_idx.get(str(data.get("edge_id")))
            if idx is not None:
                candidates.append(idx)
    return sorted(set(candidates))


def _label_rows_from_csv(
    graph: nx.MultiDiGraph,
    path: Path,
    edge_id_to_idx: dict[str, int],
    edge_meta: list[dict],
    split_name: str,
    strategy: str,
    max_rows: int | None,
    cap_pressure: float,
) -> tuple[list[int], list[list[float]], list[float], list[str]]:
    if not path.exists():
        return [], [], [], []
    df = pd.read_csv(path)
    if max_rows:
        df = df.head(max_rows)

    edge_indices: list[int] = []
    contexts: list[list[float]] = []
    targets: list[float] = []
    splits: list[str] = []

    has_edge_id = "edge_id" in df.columns
    for row in df.to_dict("records"):
        if has_edge_id and pd.notna(row.get("edge_id")):
            candidates = [edge_id_to_idx[str(row["edge_id"])]] if str(row["edge_id"]) in edge_id_to_idx else []
        else:
            node = row.get("node_id")
            candidates = _candidate_edge_indices(graph, node, strategy, edge_id_to_idx) if node in graph else []
        if not candidates:
            continue

        count = safe_float(row.get("observed_vehicle_count", row.get("vehicle_count")), 0.0)
        tc = {
            "hour": row.get("hour", 17),
            "day_of_week": row.get("day_of_week", 4),
            "month": row.get("month", 6),
            "is_weekend": row.get("is_weekend"),
            "weather": row.get("weather", "clear"),
            "temperature_c": row.get("temperature_c", 18.0),
            "precipitation_mm": row.get("precipitation_mm", 0.0),
        }
        ctx = context_vector(tc)
        for edge_idx in candidates:
            capacity = max(edge_meta[edge_idx]["capacity"], 1.0)
            pressure = min(max(count / capacity, 0.0), cap_pressure)
            edge_indices.append(edge_idx)
            contexts.append(ctx)
            targets.append(pressure)
            splits.append(split_name)

    return edge_indices, contexts, targets, splits


def build_dataset(
    graph_path: Path = DEFAULT_GRAPH_PATH,
    train_labels: Path = DEFAULT_TRAIN_LABELS,
    val_labels: Path = DEFAULT_VAL_LABELS,
    output: Path = DEFAULT_DATASET_PATH,
    label_strategy: str = "incident",
    max_label_rows: int | None = None,
    cap_pressure: float = 2.0,
    use_pagerank: bool = False,
) -> dict:
    graph = load_road_graph(graph_path)
    static = _build_static_tensors(graph, use_pagerank=use_pagerank)

    all_edges: list[int] = []
    all_contexts: list[list[float]] = []
    all_targets: list[float] = []
    all_splits: list[str] = []
    for path, split in ((train_labels, "train"), (val_labels, "val")):
        edges, contexts, targets, splits = _label_rows_from_csv(
            graph=graph,
            path=Path(path),
            edge_id_to_idx=static["edge_id_to_idx"],
            edge_meta=static["edge_meta"],
            split_name=split,
            strategy=label_strategy,
            max_rows=max_label_rows,
            cap_pressure=cap_pressure,
        )
        all_edges.extend(edges)
        all_contexts.extend(contexts)
        all_targets.extend(targets)
        all_splits.extend(splits)

    if not all_edges:
        raise RuntimeError(
            "no edge labels were built; provide edge_id labels or node_id count labels near graph nodes"
        )

    sample_edge_idx = torch.tensor(all_edges, dtype=torch.long)
    context_attr_raw = torch.tensor(all_contexts, dtype=torch.float32)
    y = torch.tensor(all_targets, dtype=torch.float32)
    split = torch.tensor([{"train": 0, "val": 1, "test": 2}.get(s, 0) for s in all_splits], dtype=torch.long)

    train_mask = split == 0
    val_mask = split == 1
    if not bool(val_mask.any()):
        generator = torch.Generator().manual_seed(42)
        order = torch.randperm(len(y), generator=generator)
        val_count = max(1, int(0.15 * len(y)))
        val_mask = torch.zeros(len(y), dtype=torch.bool)
        val_mask[order[:val_count]] = True
        train_mask = ~val_mask

    node_standardizer = fit_standardizer(static["x_raw"])
    edge_standardizer = fit_standardizer(static["edge_attr_raw"])
    context_standardizer = fit_standardizer(context_attr_raw[train_mask])
    dataset = {
        **static,
        "x": (static["x_raw"] - node_standardizer["mean"]) / node_standardizer["std"],
        "edge_attr": (static["edge_attr_raw"] - edge_standardizer["mean"]) / edge_standardizer["std"],
        "sample_edge_idx": sample_edge_idx,
        "context_attr_raw": context_attr_raw,
        "context_attr": (context_attr_raw - context_standardizer["mean"]) / context_standardizer["std"],
        "y": y,
        "train_mask": train_mask,
        "val_mask": val_mask,
        "test_mask": torch.zeros(len(y), dtype=torch.bool),
        "node_standardizer": node_standardizer,
        "edge_standardizer": edge_standardizer,
        "context_standardizer": context_standardizer,
        "node_feature_names": NODE_FEATURE_NAMES,
        "edge_feature_names": EDGE_FEATURE_NAMES,
        "context_feature_names": CONTEXT_FEATURE_NAMES,
        "label_source": {
            "train_labels": str(train_labels),
            "val_labels": str(val_labels),
            "label_strategy": label_strategy,
            "cap_pressure": cap_pressure,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(dataset, output)
    print(
        f"saved {output} nodes={static['x_raw'].shape[0]} edges={static['edge_attr_raw'].shape[0]} "
        f"samples={len(y)} train={int(train_mask.sum())} val={int(val_mask.sum())}"
    )
    return dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FlowTO GNN edge-congestion dataset.")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--train-labels", type=Path, default=DEFAULT_TRAIN_LABELS)
    parser.add_argument("--val-labels", type=Path, default=DEFAULT_VAL_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--label-strategy", choices=["incident", "outgoing", "incoming"], default="incident")
    parser.add_argument("--max-label-rows", type=int, default=None)
    parser.add_argument("--cap-pressure", type=float, default=2.0)
    parser.add_argument("--pagerank", action="store_true", help="Compute PageRank as an additional node feature.")
    args = parser.parse_args()
    build_dataset(
        graph_path=args.graph,
        train_labels=args.train_labels,
        val_labels=args.val_labels,
        output=args.output,
        label_strategy=args.label_strategy,
        max_label_rows=args.max_label_rows,
        cap_pressure=args.cap_pressure,
        use_pagerank=args.pagerank,
    )


if __name__ == "__main__":
    main()
