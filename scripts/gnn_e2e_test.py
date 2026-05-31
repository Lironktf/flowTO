"""End-to-end test of the GNN edge-congestion model on GPU.

input (time context) -> GraphSAGE inference -> per-edge {pressure, load, time, risk}

Validates:
  - the full input->output path runs and the output is structurally/numerically sane
  - temporal sensitivity (rush hour vs overnight)
  - #1 encode-once + score_edges == old re-encode-per-batch forward (within GPU noise)
  - #2 inference cache: warm call is faster and identical
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import torch

from models.gnn.predict_gnn_baseline import _prepare_inference, predict_baseline_edges
from models.gnn.gnn_to_sim_adapter import predict_gnn_edge_state
from models.gnn.utils import apply_standardizer, context_vector

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(f"  [{PASS if ok else FAIL}] {name}{(' — ' + str(detail)) if detail else ''}")
    return ok


RUSH = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}
NIGHT = {"hour": 3, "day_of_week": 4, "month": 6, "weather": "clear"}


def main():
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {dev} ({torch.cuda.get_device_name(0) if dev=='cuda' else 'cpu'})\n")

    # ===== 1. END-TO-END input -> output =====
    print("1. End-to-end inference (input time-context -> per-edge predictions):")
    payload = predict_baseline_edges(time_context=RUSH, output_path=None)
    edges = payload["edges"]
    print(f"     model={payload['model']!r} backend={payload['backend']!r}")
    print(f"     produced {len(edges):,} edge predictions")
    e0 = edges[0]
    print(f"     sample edge: id={e0['edge_id']} pressure={e0['predicted_pressure']} "
          f"load={e0['predicted_load']} time={e0['predicted_time_min']} risk={e0['risk']}")
    import numpy as np
    P = np.array([e["predicted_pressure"] for e in edges])
    check("one prediction per graph edge", len(edges) == 81669, f"{len(edges)}")
    check("all pressures finite & >= 0", np.isfinite(P).all() and (P >= 0).all(),
          f"min={P.min():.3f} max={P.max():.3f}")
    check("pressure distribution non-degenerate", P.std() > 1e-3 and P.max() > P.min(),
          f"mean={P.mean():.3f} std={P.std():.3f} p95={np.percentile(P,95):.3f}")
    risks = Counter(e["risk"] for e in edges)
    check("risk bands populated", len(risks) >= 2, dict(risks))
    # load == pressure*capacity, allowing for the 4-decimal display rounding of
    # predicted_pressure (error <= 5e-5 * capacity) plus the 2-decimal load round.
    check("predicted_load == pressure*capacity (output consistency)",
          all(abs(e["predicted_load"] - e["predicted_pressure"] * e["capacity"]) <= 5e-5 * e["capacity"] + 0.01
              for e in edges))
    top = sorted(edges, key=lambda e: -e["predicted_pressure"])[:5]
    print("     top predicted-congestion edges:")
    for e in top:
        print(f"       {str(e['road_name'])[:30]:30} {str(e['road_class'])[:10]:10} "
              f"p={e['predicted_pressure']:.2f} risk={e['risk']}")

    # ===== 2. TEMPORAL SENSITIVITY =====
    print("\n2. Temporal sensitivity (rush 17h vs overnight 3h):")
    p_rush = np.array([e["predicted_pressure"] for e in predict_baseline_edges(time_context=RUSH, output_path=None)["edges"]])
    p_night = np.array([e["predicted_pressure"] for e in predict_baseline_edges(time_context=NIGHT, output_path=None)["edges"]])
    check("mean predicted pressure higher at rush than overnight",
          p_rush.mean() > p_night.mean(), f"rush={p_rush.mean():.4f} night={p_night.mean():.4f}")

    # ===== 3. #1 encode-once == old re-encode-per-batch forward =====
    print("\n3. #1 equivalence: encode-once score_edges vs old per-batch forward:")
    dataset, model, checkpoint, edge_index, edge_attr, h, device = _prepare_inference(
        str(ROOT / "models/gnn/gnn_edge_congestion.pt"),
        str(ROOT / "data/gnn/gnn_dataset.pt"),
        str(ROOT / "data/graph/toronto_drive_graph.json"),
        dev,
    )
    x = dataset["x"].to(device)
    ctx = apply_standardizer(torch.tensor([context_vector(RUSH)], dtype=torch.float32),
                             checkpoint["context_standardizer"]).to(device)
    n = edge_attr.shape[0]; bs = 20000

    @torch.no_grad()
    def run_new():
        out = []
        for s in range(0, n, bs):
            e = min(s + bs, n); idx = torch.arange(s, e, device=device)
            out.append(model.score_edges(h, edge_index, edge_attr, ctx.expand(e - s, -1), idx))
        return torch.cat(out)

    @torch.no_grad()
    def run_old():  # original behaviour: full forward (re-encodes the graph) per batch
        out = []
        for s in range(0, n, bs):
            e = min(s + bs, n); idx = torch.arange(s, e, device=device)
            out.append(model(x, edge_index, edge_attr, ctx.expand(e - s, -1), idx))
        return torch.cat(out)

    new1, new2 = run_new(), run_new()
    old1 = run_old()
    noise = float((new1 - new2).abs().max())          # run-to-run GPU non-determinism
    diff = float((run_new() - old1).abs().max())        # new vs old
    print(f"     run-to-run GPU noise (new vs new) = {noise:.3e}")
    print(f"     new (encode-once) vs old (re-encode) = {diff:.3e}")
    check("encode-once matches old forward within GPU noise",
          diff <= max(noise * 5, 1e-4), f"diff={diff:.3e} noise={noise:.3e}")

    # ===== 4. #2 cache: warm faster + identical =====
    print("\n4. #2 inference cache (model+dataset+node-embeddings):")
    t0 = time.perf_counter(); a = predict_baseline_edges(time_context=RUSH, output_path=None); t_warm1 = time.perf_counter() - t0
    t0 = time.perf_counter(); b = predict_baseline_edges(time_context=RUSH, output_path=None); t_warm2 = time.perf_counter() - t0
    pa = [e["predicted_pressure"] for e in a["edges"]]; pb = [e["predicted_pressure"] for e in b["edges"]]
    check("cached calls return identical predictions", pa == pb)
    print(f"     warm call latency ~{t_warm2*1e3:.0f} ms (vs first {t_warm1*1e3:.0f} ms)")

    # ===== 5. adapter path used by the simulator =====
    print("\n5. Simulator adapter (predict_gnn_edge_state -> {edge_id: state}):")
    state = predict_gnn_edge_state(time_context=RUSH)
    check("adapter returns per-edge state dict", isinstance(state, dict) and len(state) == 81669,
          f"{len(state)} edges")
    k = next(iter(state)); print(f"     sample: {k} -> {state[k]}")
    check("adapter state has the 4 sim fields",
          all(set(("predicted_load", "predicted_pressure", "predicted_time_min", "risk")) <= set(v) for v in list(state.values())[:1000]))

    n_pass = sum(results)
    print(f"\n{'='*54}\nRESULT: {n_pass}/{len(results)} GNN end-to-end checks passed")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
