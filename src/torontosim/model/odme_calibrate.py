"""Ground OD magnitude in real counts via node-throughput ODME (P03 stage 2).

Replaces the invented ``nominal_total`` + target-pressure calibration (+ its
AON→equilibrium correction factor) with a data-grounded magnitude: scale the
seed gravity OD so the number of trips passing through each intersection matches
the **observed vehicle count** there (real veh/hr).

The count data (``training_dataset.csv``) is intersection-level, and the existing
``odme.odme_ipf_counts`` is generic over "things a path passes through", so we
feed it NODE keys and NODE paths directly. Per time context only a handful of
intersections have a live sensor, so the target throughput is the measured count
where a sensor exists and the (real-unit, R²≈0.72) model prediction elsewhere —
dense coverage, anchored to measurements where we have them.
"""

from __future__ import annotations

import os

import numpy as np

from .odme import odme_ipf_counts

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_COUNTS_CSV = os.path.join(_REPO_ROOT, "data", "model", "training_dataset.csv")


def load_observed_counts(time_context: dict, csv_path: str | None = None) -> dict:
    """Measured vehicle counts per node for a time context.

    Matches on ``hour`` and weekend/weekday (averaging over days/months/weather),
    since an exact (hour, dow, month, weather) slice has very few sensors.
    Returns ``{node_id: mean_vehicle_count}``. Empty if the CSV is unavailable.
    """
    try:
        import pandas as pd

        df = pd.read_csv(csv_path or _COUNTS_CSV)
    except Exception:  # noqa: BLE001 — pandas/CSV unavailable
        return {}

    hour = time_context.get("hour")
    is_weekend = int(bool(time_context.get("is_weekend", time_context.get("day_of_week", 0) >= 5)))
    sub = df[df["hour"] == hour]
    if "is_weekend" in df.columns:
        match = sub[sub["is_weekend"] == is_weekend]
        if len(match) >= 20:  # only narrow if it keeps enough sensors
            sub = match
    if sub.empty:
        return {}
    grouped = sub.groupby("node_id")["vehicle_count"].mean()
    return {int(n): float(c) for n, c in grouped.items() if c > 0}


def _node_paths(graph, od_pairs) -> dict:
    """Shortest NODE paths per (origin, destination) on free-flow time (scipy)."""
    from ..blastradius.pathcache import build_path_cache
    from ..simulation.equilibrium import network_from_graph

    net, node_index, _edge_keys = network_from_graph(graph)
    inv = {i: n for n, i in node_index.items()}
    costs = np.where(net.cap > 0, net.t0, np.inf).astype(np.float64)

    keymap = [(o, d) for (o, d) in od_pairs if o in node_index and d in node_index]
    odl = [(node_index[o], node_index[d], 1.0) for (o, d) in keymap]
    cache = build_path_cache(net, odl, costs, backend="scipy")

    paths: dict = {}
    for (o, d), link_path in zip(keymap, cache.paths):
        if not link_path:
            paths[(o, d)] = []
            continue
        seq = [int(net.tail[link_path[0]])] + [int(net.head[li]) for li in link_path]
        paths[(o, d)] = [inv[x] for x in seq]
    return paths


def build_target_throughput(graph, node_demands: dict, observed_counts: dict) -> dict:
    """Per-node target throughput: measured count where sensed, model prediction else.

    Restricted to nodes present in the graph (and with a positive value).
    """
    target = {
        n: float(node_demands[n])
        for n in graph.nodes()
        if node_demands.get(n, 0.0) and node_demands[n] > 0
    }
    for n, c in observed_counts.items():
        if n in graph and c > 0:
            target[n] = c  # measured overrides predicted
    return target


def calibrate_od_to_counts(
    graph,
    seed_od,
    target_throughput: dict,
    *,
    max_iter: int = 50,
    damping: float = 0.5,
) -> list:
    """Scale ``seed_od`` so node throughput matches ``target_throughput``.

    ``seed_od`` and the return value are ``[{"origin","destination","trips"}]``
    lists. Routing (node paths) is held fixed at free-flow during the fit.
    """
    seed = {
        (e["origin"], e["destination"]): float(e.get("trips", 0.0))
        for e in seed_od
        if e.get("trips", 0.0) > 0
    }
    if not seed:
        return list(seed_od)

    paths = _node_paths(graph, list(seed.keys()))
    adjusted = odme_ipf_counts(
        seed,
        target_throughput,
        lambda o, d: paths.get((o, d), []),
        max_iter=max_iter,
        damping=damping,
    )
    return [
        {"origin": o, "destination": d, "trips": t}
        for (o, d), t in adjusted.items()
        if t > 0
    ]


def build_grounded_od(graph, node_demands, time_context, max_pairs: int = 1500) -> dict:
    """End-to-end: gravity seed -> ODME against real counts. Returns a result dict.

    ``{"od": [...], "n_sensors": int, "target_total": float, "seed_total": float,
       "grounded_total": float}`` — the grounded OD carries real-count magnitude,
    so the caller can run with ``auto_calibrate=False`` (no invented scaling).
    """
    from .generate_od_matrix import generate_od_matrix

    seed_od = generate_od_matrix(graph, node_demands, time_context, max_pairs=max_pairs)
    observed = load_observed_counts(time_context)
    target = build_target_throughput(graph, node_demands, observed)
    grounded = calibrate_od_to_counts(graph, seed_od, target)
    return {
        "od": grounded,
        "n_sensors": sum(1 for n in observed if n in graph),
        "seed_total": sum(e["trips"] for e in seed_od),
        "grounded_total": sum(e["trips"] for e in grounded),
    }
