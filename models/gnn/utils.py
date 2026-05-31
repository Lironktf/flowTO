from __future__ import annotations

import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
DEFAULT_GRAPH_PATH = REPO_ROOT / "data" / "graph" / "toronto_drive_graph.json"
DEFAULT_DATASET_PATH = REPO_ROOT / "data" / "gnn" / "gnn_dataset.pt"
DEFAULT_MODEL_PATH = PACKAGE_DIR / "gnn_edge_congestion.pt"
DEFAULT_METRICS_PATH = REPO_ROOT / "data" / "gnn" / "training_metrics.json"
DEFAULT_PREDICTIONS_PATH = REPO_ROOT / "data" / "results" / "gnn_baseline_predictions.json"
DEFAULT_TRAIN_LABELS = REPO_ROOT / "data" / "model" / "training_dataset.csv"
DEFAULT_VAL_LABELS = REPO_ROOT / "data" / "model" / "validation_dataset.csv"

DOWNTOWN_LAT = 43.6510
DOWNTOWN_LON = -79.3810

ROAD_CLASS_RANK = {
    "motorway": 6,
    "trunk": 5,
    "primary": 4,
    "secondary": 3,
    "tertiary": 2,
    "unclassified": 1,
    "residential": 1,
    "living_street": 1,
    "service": 1,
}
ROAD_CLASS_ORDER = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "service",
    "unclassified",
    "living_street",
    "other",
]

NODE_FEATURE_NAMES = [
    "lat",
    "lon",
    "degree",
    "in_degree",
    "out_degree",
    "distance_to_downtown_km",
    "pagerank",
]
EDGE_FEATURE_NAMES = [
    "length_m",
    "road_class_rank",
    "lanes",
    "speed_kmh",
    "capacity",
    "base_time_min",
    "one_way",
    "bearing_sin",
    "bearing_cos",
    "from_node_degree",
    "to_node_degree",
    *[f"road_class_{name}" for name in ROAD_CLASS_ORDER],
]
CONTEXT_FEATURE_NAMES = [
    "hour_norm",
    "day_of_week_norm",
    "month_norm",
    "is_weekend",
    "rush_hour",
    "weather_clear",
    "weather_rain",
    "weather_snow",
    "temperature_c_norm",
    "precipitation_mm_norm",
    "season_winter",
    "season_spring",
    "season_summer",
    "season_fall",
]


def ensure_repo_importable() -> None:
    src = str(REPO_ROOT / "src")
    root = str(REPO_ROOT)
    for item in (src, root):
        if item not in sys.path:
            sys.path.insert(0, item)


def load_road_graph(path: str | os.PathLike[str] | None = None):
    ensure_repo_importable()
    from torontosim.graph.routing import import_graph_json

    return import_graph_json(str(path or DEFAULT_GRAPH_PATH))


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.benchmark = True


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def normalize_time_context(time_context: dict[str, Any] | None) -> dict[str, Any]:
    tc = dict(time_context or {})
    tc["hour"] = int(tc.get("hour", 17))
    tc["day_of_week"] = int(tc.get("day_of_week", 4))
    tc["month"] = int(tc.get("month", 6))
    tc["is_weekend"] = int(tc.get("is_weekend", 1 if tc["day_of_week"] >= 5 else 0))
    tc["weather"] = str(tc.get("weather") or "clear").lower()
    tc["temperature_c"] = safe_float(tc.get("temperature_c"), 18.0)
    tc["precipitation_mm"] = safe_float(tc.get("precipitation_mm"), 0.0)
    return tc


def is_rush_hour(hour: int) -> int:
    return int(hour in (7, 8, 9, 16, 17, 18, 19))


def season_one_hot(month: int) -> list[float]:
    if month in (12, 1, 2):
        return [1.0, 0.0, 0.0, 0.0]
    if month in (3, 4, 5):
        return [0.0, 1.0, 0.0, 0.0]
    if month in (6, 7, 8):
        return [0.0, 0.0, 1.0, 0.0]
    return [0.0, 0.0, 0.0, 1.0]


def context_vector(time_context: dict[str, Any] | None) -> list[float]:
    tc = normalize_time_context(time_context)
    weather = tc["weather"]
    return [
        tc["hour"] / 23.0,
        tc["day_of_week"] / 6.0,
        tc["month"] / 12.0,
        float(tc["is_weekend"]),
        float(is_rush_hour(tc["hour"])),
        float(weather in ("clear", "cloud", "cloudy", "overcast")),
        float(weather in ("rain", "fog", "drizzle")),
        float(weather == "snow"),
        tc["temperature_c"] / 40.0,
        min(tc["precipitation_mm"], 50.0) / 50.0,
        *season_one_hot(tc["month"]),
    ]


def road_class_rank(road_class: Any) -> int:
    return ROAD_CLASS_RANK.get(str(road_class or "").lower(), 1)


def road_class_one_hot(road_class: Any) -> list[float]:
    key = str(road_class or "").lower()
    if key not in ROAD_CLASS_ORDER:
        key = "other"
    return [1.0 if key == item else 0.0 for item in ROAD_CLASS_ORDER]


def bearing_features(from_node: dict[str, Any], to_node: dict[str, Any]) -> tuple[float, float]:
    lat1 = math.radians(safe_float(from_node.get("lat", from_node.get("y"))))
    lat2 = math.radians(safe_float(to_node.get("lat", to_node.get("y"))))
    dlon = math.radians(safe_float(to_node.get("lon", to_node.get("x"))) - safe_float(from_node.get("lon", from_node.get("x"))))
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    angle = math.atan2(y, x)
    return math.sin(angle), math.cos(angle)


def pressure_to_risk(pressure: float) -> str:
    if pressure < 0.50:
        return "low"
    if pressure < 0.75:
        return "moderate"
    if pressure < 1.00:
        return "high"
    return "severe"


def pressure_time_multiplier(pressure: float) -> float:
    if pressure < 0.50:
        return 1.0
    if pressure < 0.75:
        return 1.2
    if pressure < 1.00:
        return 1.6
    if pressure < 1.25:
        return 2.2
    return 3.0


def fit_standardizer(tensor: torch.Tensor) -> dict[str, torch.Tensor]:
    mean = tensor.mean(dim=0)
    std = tensor.std(dim=0)
    std = torch.where(std < 1e-6, torch.ones_like(std), std)
    return {"mean": mean, "std": std}


def apply_standardizer(tensor: torch.Tensor, standardizer: dict[str, torch.Tensor]) -> torch.Tensor:
    return (tensor - standardizer["mean"].to(tensor.device)) / standardizer["std"].to(tensor.device)


def risk_bucket_tensor(values: torch.Tensor) -> torch.Tensor:
    return torch.bucketize(values, torch.tensor([0.50, 0.75, 1.00], device=values.device))


def rmse(pred: torch.Tensor, target: torch.Tensor) -> float:
    return float(torch.sqrt(torch.mean((pred - target) ** 2)).detach().cpu())


def mae(pred: torch.Tensor, target: torch.Tensor) -> float:
    return float(torch.mean(torch.abs(pred - target)).detach().cpu())


def r2_score(pred: torch.Tensor, target: torch.Tensor) -> float:
    ss_res = torch.sum((target - pred) ** 2)
    ss_tot = torch.sum((target - torch.mean(target)) ** 2)
    if float(ss_tot.detach().cpu()) <= 1e-12:
        return 0.0
    return float((1.0 - ss_res / ss_tot).detach().cpu())


def classification_accuracy(pred: torch.Tensor, target: torch.Tensor) -> float:
    return float((risk_bucket_tensor(pred) == risk_bucket_tensor(target)).float().mean().detach().cpu())


def write_json(path: str | os.PathLike[str], payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def torch_device(prefer_cuda: bool = True) -> torch.device:
    if prefer_cuda and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def device_report(device: torch.device) -> dict[str, Any]:
    report: dict[str, Any] = {
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_used": device.type == "cuda",
        "cuda_version": torch.version.cuda,
    }
    if torch.cuda.is_available():
        report["cuda_device_count"] = torch.cuda.device_count()
        report["cuda_device_name"] = torch.cuda.get_device_name(0)
        report["cudnn_version"] = torch.backends.cudnn.version()
    for name in ("cudf", "cugraph"):
        try:
            mod = __import__(name)
            report[f"{name}_available"] = True
            report[f"{name}_version"] = getattr(mod, "__version__", None)
        except Exception:
            report[f"{name}_available"] = False
    try:
        import torch_geometric

        report["torch_geometric_available"] = True
        report["torch_geometric_version"] = torch_geometric.__version__
    except Exception:
        report["torch_geometric_available"] = False
    return report

