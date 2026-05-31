"""Full-coverage GNN baseline — the no-edit "usual congestion" view.

The GraphSAGE model predicts a per-edge **pressure ratio** directly for EVERY edge
of the road graph; ``load = pressure × capacity`` (see models/gnn/predict_gnn_baseline.py).
That IS the baseline view: full coverage (all ~81.7k edges), one fast forward pass
per hour, no OD and no equilibrium. Validated on this box: the 175 MB tensor bundle
loads in ~0.5s and a whole 24-hour day is ~0.3s once warm.

Edits still run the equilibrium engine in ``api/recompute.py`` so closures/surges
actually reroute — the GNN is not intervention-aware, so it stays the baseline only.

The bundle (dataset tensors + model) is loaded ONCE (module cache, on the inference
device) and reused across all 24 hourly forward passes and every day/month request.
"""

from __future__ import annotations

import os
import sys
import threading
from collections import OrderedDict

from .encoding import pack_day_frame

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_ART_DIR = os.path.join(_REPO_ROOT, "data", "simulation")

# Default baseline view — matches the front-end DEFAULT_DAY_OF_YEAR=161 (Wed 10 Jun):
# day_of_week Monday=0 → Wed=2, month=6.
DEFAULT_DOW = 2
DEFAULT_MONTH = 6

_bundle = None
_bundle_lock = threading.Lock()
_speed_cache: dict = {}
_blob_cache: "OrderedDict" = OrderedDict()
_blob_lock = threading.Lock()
_BLOB_MAX = 8


def _ensure_models_on_path() -> None:
    # The GNN package lives at <repo>/models/gnn (outside the torontosim package).
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)


def get_bundle() -> dict:
    """Load (once) the GNN dataset tensors + model onto the inference device."""
    global _bundle
    if _bundle is not None:
        return _bundle
    with _bundle_lock:
        if _bundle is not None:
            return _bundle
        _ensure_models_on_path()
        from pathlib import Path

        from models.gnn.predict_gnn_baseline import _load_or_build_dataset, load_checkpoint_model
        from models.gnn.utils import (
            DEFAULT_DATASET_PATH,
            DEFAULT_GRAPH_PATH,
            DEFAULT_MODEL_PATH,
            torch_device,
        )

        device = torch_device(prefer_cuda=True)
        dataset = _load_or_build_dataset(Path(DEFAULT_DATASET_PATH), Path(DEFAULT_GRAPH_PATH))
        model, checkpoint = load_checkpoint_model(Path(DEFAULT_MODEL_PATH), device)
        _bundle = {
            "device": device,
            "x": dataset["x"].to(device),
            "edge_index": dataset["edge_index"].to(device),
            "edge_attr": dataset["edge_attr"].to(device),
            "edge_meta": dataset["edge_meta"],
            "checkpoint": checkpoint,
            "model": model,
        }
        return _bundle


def _edge_pressures(time_context: dict, batch_size: int = 20000):
    """Per-edge predicted pressure (numpy array, aligned to ``edge_meta`` order)."""
    import torch

    from models.gnn.utils import apply_standardizer, context_vector

    b = get_bundle()
    device = b["device"]
    raw = torch.tensor([context_vector(time_context)], dtype=torch.float32)
    ctx = apply_standardizer(raw, b["checkpoint"]["context_standardizer"]).to(device)
    n = int(b["edge_attr"].shape[0])
    out = []
    with torch.no_grad():
        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            idx = torch.arange(start, end, dtype=torch.long, device=device)
            pred = b["model"](
                b["x"], b["edge_index"], b["edge_attr"], ctx.expand(end - start, -1), idx
            )
            out.append(pred.detach().cpu())
    return torch.cat(out).numpy()


def _speed_map(graph) -> dict:
    """edge_id -> speed_kmh (built once for the live graph; used to derive eff speed)."""
    key = id(graph)
    cached = _speed_cache.get(key)
    if cached is None:
        cached = {
            d.get("edge_id"): float(d.get("speed_kmh") or 0.0)
            for _u, _v, d in graph.edges(data=True)
            if d.get("edge_id") is not None
        }
        _speed_cache.clear()  # only ever track the single live graph
        _speed_cache[key] = cached
    return cached


def hour_records(state, time_context: dict) -> list:
    """Record5 tuples ``(idx, load, speed, pressure, closure)`` for EVERY edge, one hour."""
    from models.gnn.utils import pressure_time_multiplier

    pressures = _edge_pressures(time_context)
    b = get_bundle()
    edge_meta = b["edge_meta"]
    speed = _speed_map(state.graph)
    recs = []
    for i in range(len(pressures)):
        meta = edge_meta[i]
        eid = meta["edge_id"]
        idx = state.edge_index.get(eid)
        if idx is None:
            continue
        p = max(float(pressures[i]), 0.0)
        cap = float(meta.get("capacity") or 0.0)
        mult = pressure_time_multiplier(p)  # travel-time penalty as pressure rises
        spd = speed.get(eid, 0.0)
        eff_speed = (spd / mult) if mult else spd
        recs.append((idx, float(p * cap), float(eff_speed), float(p), 0))
    return recs


def day_records(state, dow: int, month: int) -> list:
    """24 Record5 lists (one per hour) — the GNN baseline day, full coverage, clear weather."""
    return [
        hour_records(
            state, {"hour": h, "day_of_week": int(dow), "month": int(month), "weather": "clear"}
        )
        for h in range(24)
    ]


def artifact_path(dow: int, month: int) -> str:
    return os.path.join(_ART_DIR, f"baseline_gnn_dow{int(dow)}_m{int(month)}.bin")


def _pack_day(day: list) -> bytes:
    return b"".join(pack_day_frame(h, 0, recs) for h, recs in enumerate(day))


def day_blob(state, dow: int, month: int) -> bytes:
    """Packed 24-frame GNN baseline-day blob (the shape the front-end ingests).

    Resolution: in-memory LRU → on-disk artifact → compute via the GNN. Cached so a
    repeated day/month is instant; the default day is warmed at startup.
    """
    key = (int(dow), int(month))
    with _blob_lock:
        blob = _blob_cache.get(key)
        if blob is not None:
            _blob_cache.move_to_end(key)
            return blob
    path = artifact_path(dow, month)
    if os.path.exists(path):
        with open(path, "rb") as fh:
            blob = fh.read()
    else:
        blob = _pack_day(day_records(state, dow, month))
    with _blob_lock:
        _blob_cache[key] = blob
        _blob_cache.move_to_end(key)
        while len(_blob_cache) > _BLOB_MAX:
            _blob_cache.popitem(last=False)
    return blob


def write_artifact(state, dow: int, month: int) -> str:
    """Compute the GNN baseline day and persist it as a .bin artifact (offline precompute)."""
    blob = _pack_day(day_records(state, dow, month))
    os.makedirs(_ART_DIR, exist_ok=True)
    path = artifact_path(dow, month)
    with open(path, "wb") as fh:
        fh.write(blob)
    with _blob_lock:
        _blob_cache[(int(dow), int(month))] = blob
    return path


def warm_default(state) -> None:
    """Warm the heavy bundle (so EVERY day/month is then ~0.3s) and the default
    day's blob (called in the startup background thread)."""
    get_bundle()
    day_blob(state, DEFAULT_DOW, DEFAULT_MONTH)
