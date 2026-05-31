"""P13 §B — scenario generator (Stage-1 sim pre-training data).

Script the deterministic Frank-Wolfe sim to emit ``(intervention → equilibrium flow)``
pairs at scale: sample a road-class-stratified intervention (closure or opening),
re-solve on the same OD, and record the per-edge residual ``Δflow = sim_int − sim_open``.
These unlimited, physics-correct labels teach the GNN how the network reroutes (Stage-1),
before the thin real fine-tune (Stage-2).

The sampling + pair-building logic is dependency-injected on the two simulate callbacks
so it unit-tests without the sim; ``generate_from_sim`` is the thin real adapter over
``simulation.simulate_traffic`` (Spark/GB10). See ``docs/specs/13-feedback-loop.md`` §B.
"""

from __future__ import annotations

from typing import Callable, Mapping

import numpy as np
import pandas as pd

# arterials/collectors reroute more → sample them more often (bias, not exclusivity)
ROAD_CLASS_WEIGHT = {
    "motorway": 6, "trunk": 5, "primary": 5, "secondary": 4, "tertiary": 3,
    "residential": 2, "service": 1, "unclassified": 2, "living_street": 1, "other": 2,
}


def sample_interventions(
    edges: pd.DataFrame,
    *,
    n: int,
    seed: int,
    p_closure: float = 0.7,
    capacity_down: float = 0.5,
    capacity_up: float = 1.5,
) -> list[dict]:
    """Sample ``n`` road-class-stratified interventions (closures + openings).

    ``edges`` needs ``edge_id`` and ``road_class``. Deterministic for a fixed seed
    (uses a local RNG, not the global module). Each item:
    ``{"id", "edge_id", "sign", "ops"}`` where ``ops`` are scenario mutations.
    """
    rng = np.random.default_rng(seed)
    n = int(min(n, len(edges)))
    if n == 0:
        return []
    weights = np.array(
        [ROAD_CLASS_WEIGHT.get(str(rc), 2) for rc in edges["road_class"]], dtype=np.float64
    )
    weights = weights / weights.sum()
    pick = rng.choice(len(edges), size=n, replace=False, p=weights)

    out: list[dict] = []
    for i, idx in enumerate(pick):
        eid = str(edges.iloc[int(idx)]["edge_id"])
        if rng.random() < p_closure:
            sign, ops = "closure", [{"op": "close_edge", "edge_id": eid}]
            if rng.random() < 0.5:  # half of closures are partial capacity cuts
                ops = [{"op": "change_capacity", "edge_id": eid, "multiplier": capacity_down}]
        else:
            sign = "opening"
            ops = [{"op": "change_capacity", "edge_id": eid, "multiplier": capacity_up}]
        out.append({"id": f"sim{i:05d}", "edge_id": eid, "sign": sign, "ops": ops})
    return out


def generate_pairs(
    interventions: list[dict],
    simulate_open: Callable[[], Mapping[str, float]],
    simulate_intervened: Callable[[list], Mapping[str, float]],
) -> pd.DataFrame:
    """Per scenario, the per-edge residual flow over the open-road equilibrium.

    Returns long-format rows ``[scenario_id, edge_id, closed_edge, sign, sim_open,
    sim_int, delta_flow]``. ``delta_flow`` (= ``sim_int − sim_open``) is the Stage-1
    target (P13 normalizes to Δpressure by capacity).
    """
    sim_open = simulate_open()
    rows: list[dict] = []
    for iv in interventions:
        sim_int = simulate_intervened(iv["ops"])
        for edge_id, base in sim_open.items():
            after = float(sim_int.get(edge_id, base))
            rows.append(
                {
                    "scenario_id": iv["id"],
                    "edge_id": edge_id,
                    "closed_edge": iv.get("edge_id"),
                    "sign": iv["sign"],
                    "sim_open": float(base),
                    "sim_int": after,
                    "delta_flow": after - float(base),
                }
            )
    return pd.DataFrame(
        rows,
        columns=["scenario_id", "edge_id", "closed_edge", "sign", "sim_open", "sim_int", "delta_flow"],
    )


def generate_from_sim(graph, od_matrix, *, n: int, seed: int) -> pd.DataFrame:  # pragma: no cover - sim on GB10
    """Real adapter: sample interventions over the graph's edges and run the sim."""
    from .groundtruth.counterfactual import simulate_open_intervened

    edges = pd.DataFrame(
        [
            {"edge_id": str(d.get("edge_id") or f"{u}-{v}-{k}"), "road_class": d.get("road_class", "other")}
            for u, v, k, d in graph.edges(keys=True, data=True)
        ]
    )
    interventions = sample_interventions(edges, n=n, seed=seed)
    simulate_open, simulate_intervened = simulate_open_intervened(graph, od_matrix)
    return generate_pairs(interventions, simulate_open, simulate_intervened)
