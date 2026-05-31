"""GB10-only orchestration inputs for the Stage-2 pipeline.

Three things the Stage-1 pretrain and the Stage-2 fine-tune both need on the box:
the full **Centreline** graph, a **counts-grounded** OD (so ``sim_open`` lands on the
same scale as the observed TMC counts — without this ``r_obs`` is dominated by sim
error), and the real **TMC records**. The heavy model/sim stack is imported lazily;
this module only runs where torch/cuDF/the sim live. See ``docs/specs/13-feedback-loop.md``.
"""

from __future__ import annotations

import os

# weekday PM peak — the regime real closures are most often surveyed in
DEFAULT_TIME_CONTEXT = {"hour": 17, "day_of_week": 2, "month": 6, "weather": "clear"}

DEFAULT_GRAPH = os.path.join("data", "graph", "toronto_centreline_graph.json")
TMC_PARQUET = os.path.join("data", "parquet", "tmc.parquet")
TMC_RAW = os.path.join("data", "raw", "tmc_raw_data_2020_2029.csv")


def load_graph(path: str = DEFAULT_GRAPH, *, data_dir: str = "data"):  # pragma: no cover - GB10
    """Load the Centreline graph JSON, building it from the parquet store if absent."""
    from torontosim.graph.routing import import_graph_json

    if os.path.exists(path):
        return import_graph_json(path)
    from torontosim.graph.build import build_centreline
    from torontosim.graph.routing import export_graph_json

    graph = build_centreline(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    export_graph_json(graph, path)
    return graph


def load_tmc_records():  # pragma: no cover - GB10
    """Real TMC rows as a list of dicts (parquet store preferred, raw CSV fallback)."""
    if os.path.exists(TMC_PARQUET):
        import pyarrow.parquet as pq

        return pq.read_table(TMC_PARQUET).to_pylist()
    import pandas as pd

    return pd.read_csv(TMC_RAW, low_memory=False).to_dict("records")


def grounded_od(
    graph, *, time_context=None, max_pairs: int = 3000, tmc_records=None, method: str = "app"
):  # pragma: no cover - GB10
    """A TMC-counts-grounded OD.

    ``method="app"`` (default) builds the OD **exactly as ``api/recompute.py`` does**
    (``build_grounded_od``, ``max_pairs=3000``) so the model's ``sim_open`` input matches
    the app's runtime baseline — the residual then transfers to the app by construction
    (no train/serve distribution gap). ``method="ipf_counts"`` keeps the older
    ``generate_od_matrix(calibration="ipf_counts")`` path.
    """
    from torontosim.model.predict_node_demand import (
        load_demand_model,
        predict_node_demand,
    )

    tc = time_context or DEFAULT_TIME_CONTEXT
    demands = predict_node_demand(graph, load_demand_model(), tc)
    if method == "app":
        from torontosim.model.odme_calibrate import build_grounded_od

        return build_grounded_od(graph, demands, tc, max_pairs=max_pairs)["od"]

    from torontosim.model.generate_od_matrix import generate_od_matrix

    if tmc_records is None:
        tmc_records = load_tmc_records()
    return generate_od_matrix(
        graph,
        demands,
        tc,
        max_pairs=max_pairs,
        calibration="ipf_counts",
        tmc_records=tmc_records,
    )
