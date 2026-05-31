"""Verify that a demand model satisfies the contract and is reproducible.

Drop in ANY model and confirm it is safe to simulate with, before trusting it:

    python scripts/verify_model.py                          # default committed model
    python scripts/verify_model.py --kind gnn               # the GraphSAGE model
    python scripts/verify_model.py --model-path my_model.pkl
    python scripts/verify_model.py --sim                    # also run a mini simulation

Checks: contract (.predict / kind dispatch), manifest/provenance, feature-order
compatibility, output sanity (one finite, non-negative, non-degenerate value per
node), and reproducibility (two predictions are identical).
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np

from torontosim.graph.routing import import_graph_json
from torontosim.model.contract import check_compatible, manifest_from_payload
from torontosim.model.features import FEATURE_ORDER
from torontosim.model.predict_node_demand import load_demand_model, predict_node_demand

GRAPH_JSON = os.path.join(_ROOT, "data", "graph", "toronto_drive_graph.json")
TC = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}

_checks: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _checks.append(bool(ok))
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}{(' — ' + detail) if detail else ''}")
    return bool(ok)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-path", default=None, help="path to a model .pkl")
    ap.add_argument("--kind", default="auto", help="auto | xgboost | gnn")
    ap.add_argument("--sim", action="store_true", help="also run a mini OD+simulation sanity pass")
    args = ap.parse_args()

    print("1. Load model + read manifest/provenance:")
    if args.model_path:
        model = load_demand_model(model_path=args.model_path, kind=args.kind)
    else:
        model = load_demand_model(kind=args.kind)
    man = manifest_from_payload(model if isinstance(model, dict) else {})
    kind = model.get("kind") if isinstance(model, dict) else type(model).__name__
    print(f"     kind={kind!r}")
    if man:
        print(f"     schema_version={man.schema_version} seed={man.seed} "
              f"git={man.git_commit} created={man.created_at}")
        print(f"     trained_on={man.training_data_path} sha256={(man.training_data_sha256 or '')[:12]} "
              f"rows={man.training_rows} metrics={man.metrics}")
    else:
        print("     (no manifest — legacy or runtime-built model)")

    print("\n2. Contract + compatibility:")
    problems = check_compatible(model if isinstance(model, dict) else {"kind": kind,
                                "feature_order": getattr(model, "feature_order", FEATURE_ORDER)},
                                expected_feature_order=FEATURE_ORDER)
    check("feature-order / schema compatible", not problems,
          "; ".join(problems) if problems else f"{len(FEATURE_ORDER)} features")

    print("\n3. Prediction sanity (input context -> per-node demand):")
    graph = import_graph_json(GRAPH_JSON)
    n_nodes = graph.number_of_nodes()
    demand = predict_node_demand(graph, model, TC)
    vals = np.array(list(demand.values()), dtype=float)
    check("produced predictions", len(demand) > 0, f"{len(demand):,}/{n_nodes:,} nodes")
    check("all finite", bool(np.isfinite(vals).all()))
    check("all non-negative", bool((vals >= 0).all()), f"min={vals.min():.2f}")
    check("non-degenerate (varies across nodes)", float(vals.std()) > 1e-6,
          f"mean={vals.mean():.1f} std={vals.std():.1f} max={vals.max():.0f}")

    print("\n4. Reproducibility (same model + same context -> identical output):")
    demand2 = predict_node_demand(graph, model, TC)
    same = demand.keys() == demand2.keys() and all(
        demand[k] == demand2[k] for k in demand
    )
    check("two predictions are identical", same)

    print("\n5. Temporal response (rush 17h vs overnight 3h):")
    night = predict_node_demand(graph, model, {**TC, "hour": 3})
    nvals = np.array([night[k] for k in demand], dtype=float)
    check("mean demand higher at rush than overnight",
          vals.mean() > nvals.mean(), f"rush={vals.mean():.1f} night={nvals.mean():.1f}")

    if args.sim:
        print("\n6. Mini OD + simulation sanity pass:")
        from torontosim.model.odme_calibrate import build_grounded_od
        from torontosim.simulation.simulate_traffic import simulate_traffic

        od = build_grounded_od(graph, demand, TC, max_pairs=500)["od"]
        result = simulate_traffic(
            graph, od, iterations=2, k_paths=3, time_context=TC, node_demands=demand,
            engine="equilibrium", backend="scipy", congestion_model="bpr",
            rgap_target=1e-2, max_equilibrium_iter=10, auto_calibrate=False,
        )
        s = result["summary"]
        check("simulation produced assigned trips", s["total_assigned_trips"] > 0,
              f"trips={s['total_assigned_trips']:,.0f}")
        check("average pressure in plausible range", 0.0 < s["average_pressure"] < 5.0,
              f"avg_P={s['average_pressure']:.3f}")

    n_pass = sum(_checks)
    print(f"\n{'='*56}\nRESULT: {n_pass}/{len(_checks)} checks passed — "
          f"{'MODEL OK' if n_pass == len(_checks) else 'MODEL NOT SAFE TO SIMULATE'}")
    return 0 if n_pass == len(_checks) else 1


if __name__ == "__main__":
    sys.exit(main())
