"""P14 Phase 6 — sim-counterfactual residual (fills missing baselines).

The GNN (P13) trains on the **residual over the sim**. For each intervention we run
the deterministic Frank-Wolfe sim **open** and **intervened** on the same OD; the
sim's *open* run is the counterfactual "before", so a real pre-survey is not required.
At each affected/nearby link we emit:

  * ``sim_open``  — equilibrium flow with the road open
  * ``sim_int``   — equilibrium flow with the intervention applied
  * ``r_sim``     = sim_int − sim_open          (the sim's own predicted residual)
  * ``r_obs``     = observed − sim_open         (the real residual — the P13 target)

A link with no observed in-window count yields **no** residual row (no fabrication).
The residual math here is dependency-injected on the two simulate callbacks, so it
unit-tests without spinning the full sim; ``simulate_open_intervened`` is the thin
real adapter over ``simulation.simulate_traffic`` (Spark/GB10). See
``docs/specs/14-closure-dataset.md`` Phase 6.
"""

from __future__ import annotations

from typing import Callable, Mapping

import pandas as pd


def compute_residuals(
    interventions: list[dict],
    observed: Mapping[tuple, float],
    simulate_open: Callable[[], Mapping[str, float]],
    simulate_intervened: Callable[[list], Mapping[str, float]],
) -> pd.DataFrame:
    """Residual rows for every observed link of every intervention.

    ``interventions``: ``[{"ID": ..., "ops": [...]}, ...]`` (ops = scenario mutations).
    ``observed``: ``{(ID, edge_id): observed_flow}`` — only these links get a row.
    ``simulate_open()`` → ``{edge_id: flow}`` (computed once; OD/graph fixed).
    ``simulate_intervened(ops)`` → ``{edge_id: flow}`` for that intervention.
    """
    sim_open = simulate_open()
    rows: list[dict] = []
    for iv in interventions:
        sim_int = simulate_intervened(iv["ops"])
        for (iv_id, edge_id), obs in observed.items():
            if iv_id != iv["ID"] or edge_id not in sim_open:
                continue  # no sim baseline for this link → no fabricated residual
            base = sim_open[edge_id]
            after = sim_int.get(edge_id, base)
            rows.append(
                {
                    "ID": iv_id,
                    "edge_id": edge_id,
                    "sim_open": base,
                    "sim_int": after,
                    "r_sim": after - base,
                    "r_obs": obs - base,
                }
            )
    return pd.DataFrame(
        rows, columns=["ID", "edge_id", "sim_open", "sim_int", "r_sim", "r_obs"]
    )


def simulate_open_intervened(graph, od_matrix):  # pragma: no cover - needs the sim on the GB10
    """Thin real adapter: build (open, intervened) callbacks over the P04 sim.

    Returns ``(simulate_open, simulate_intervened)`` for ``compute_residuals``. Runs
    the deterministic equilibrium engine; the open solve is cached. Imported lazily so
    this module stays importable (and unit-testable) without the simulation stack.
    """
    from torontosim.simulation.simulate_traffic import apply_scenario, simulate_traffic

    def _flows(result) -> dict[str, float]:
        return {
            str(d.get("edge_id") or f"{u}-{v}-{k}"): float(d.get("load", 0.0))
            for u, v, k, d in result["graph"].edges(keys=True, data=True)
        }

    _open_cache: dict[str, dict] = {}

    def simulate_open() -> dict[str, float]:
        if "r" not in _open_cache:
            _open_cache["r"] = simulate_traffic(
                graph, od_matrix, engine="equilibrium", backend="scipy",
                auto_calibrate=False, copy_graph=True,
            )
        return _flows(_open_cache["r"])

    def simulate_intervened(ops: list) -> dict[str, float]:
        res = simulate_traffic(
            graph, od_matrix, engine="equilibrium", backend="scipy",
            auto_calibrate=False, copy_graph=True,
        )
        apply_scenario(res["graph"], ops)
        res2 = simulate_traffic(
            res["graph"], od_matrix, engine="equilibrium", backend="scipy",
            auto_calibrate=False, copy_graph=False,
        )
        return _flows(res2)

    return simulate_open, simulate_intervened
