"""CPU vs GPU all-or-nothing SSSP benchmark on the real Toronto graph.

Isolates the routing hot path: builds the compact Network from the Toronto
graph, generates a fixed pseudo-random OD set, and times ``all_or_nothing`` on
the CPU heap-Dijkstra backend vs the cuGraph SSSP backend. Also checks the GPU
flow matches the CPU flow (L1 / max abs diff) so we measure correctness AND
speed in one shot.

Usage (on the Spark, inside ~/flowto-venv):
    PYTHONPATH=~/torontosim/src python scripts/spark/bench_gpu_sssp.py \
        --graph ~/torontosim/data/graph/toronto_drive_graph.json \
        --origins 200 --dests-per-origin 8 --repeats 3
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np


def _load_net(graph_path):
    from torontosim.graph.routing import import_graph_json
    from torontosim.simulation.equilibrium import network_from_graph

    graph = import_graph_json(graph_path)
    net, node_index, edge_keys = network_from_graph(graph)
    return graph, net, node_index, edge_keys


def _make_od(net, n_origins, dests_per_origin, seed=1234):
    """Deterministic OD set: {origin: [(dest, demand), ...]} over node 0..n-1."""
    rng = np.random.default_rng(seed)
    n = net.n_nodes
    origins = rng.choice(n, size=min(n_origins, n), replace=False)
    od_by_origin = {}
    for o in origins:
        dests = rng.choice(n, size=min(dests_per_origin, n), replace=False)
        od_by_origin[int(o)] = [(int(d), 1.0) for d in dests if int(d) != int(o)]
    return od_by_origin


def _time(fn, repeats):
    # one warm-up (GPU context / first-call init), then timed repeats
    fn()
    best = float("inf")
    total = 0.0
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        total += dt
        best = min(best, dt)
    return best, total / repeats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--origins", type=int, default=200)
    ap.add_argument("--dests-per-origin", type=int, default=8)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args(argv)

    from torontosim.simulation import backends
    from torontosim.simulation.backends import cpu as cpu_backend

    print(f"loading graph: {args.graph}")
    _graph, net, _ni, _ek = _load_net(args.graph)
    print(f"network: {net.n_nodes:,} nodes · {net.n_links:,} links")
    print(f"backends available: {backends.available_backends()}")

    od = _make_od(net, args.origins, args.dests_per_origin)
    n_pairs = sum(len(v) for v in od.values())
    print(f"OD set: {len(od):,} origins · {n_pairs:,} pairs · repeats={args.repeats}\n")

    # free-flow costs (t0); closed/zero-cap links -> inf
    costs = np.where(net.cap > 0, net.t0, np.inf).astype(np.float64)

    # --- CPU ---
    cpu_flow_holder = {}

    def run_cpu():
        cpu_flow_holder["f"] = cpu_backend.all_or_nothing(net, costs, od)

    cpu_best, cpu_avg = _time(run_cpu, args.repeats)
    cpu_flow = cpu_flow_holder["f"]
    print(f"CPU  all_or_nothing : best={cpu_best*1e3:8.1f} ms   avg={cpu_avg*1e3:8.1f} ms")

    # --- scipy vectorized CPU (multi-source Dijkstra in one C call) ---
    try:
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import dijkstra as sp_dijkstra

        finite = np.isfinite(costs)
        # parallel edges: keep min-cost per (tail,head); scipy csr sums duplicates
        eff = np.where(finite, costs, np.inf)
        order = np.lexsort((eff, net.head[:], net.tail[:]))
        seen = {}
        rows, cols, data = [], [], []
        for li in order:
            if not finite[li]:
                continue
            key = (int(net.tail[li]), int(net.head[li]))
            if key in seen:
                continue
            seen[key] = li
            rows.append(key[0]); cols.append(key[1]); data.append(float(costs[li]))
        csr = csr_matrix((data, (rows, cols)), shape=(net.n_nodes, net.n_nodes))
        origins = sorted(od)
        oidx = {o: i for i, o in enumerate(origins)}

        sp_holder = {}

        def run_scipy():
            dist, pred = sp_dijkstra(csr, directed=True, indices=origins, return_predecessors=True)
            flow = np.zeros(net.n_links, dtype=np.float64)
            for o in origins:
                pr = pred[oidx[o]]
                for dest, demand in od[o]:
                    v = dest
                    while v != o and v >= 0:
                        p = pr[v]
                        if p < 0:
                            break
                        li = seen.get((int(p), int(v)))
                        if li is not None:
                            flow[li] += demand
                        v = p
            sp_holder["f"] = flow

        sp_best, sp_avg = _time(run_scipy, args.repeats)
        print(f"scipy all_or_nothing : best={sp_best*1e3:8.1f} ms   avg={sp_avg*1e3:8.1f} ms"
              f"   ({cpu_best/sp_best:.1f}x vs CPU-heap)")
    except Exception as exc:  # noqa: BLE001
        print(f"scipy variant skipped: {exc!r}")

    # --- GPU ---
    if "gpu" in backends.available_backends():
        from torontosim.simulation.backends import gpu as gpu_backend

        gpu_flow_holder = {}

        def run_gpu():
            gpu_flow_holder["f"] = gpu_backend.all_or_nothing(net, costs, od)

        gpu_best, gpu_avg = _time(run_gpu, args.repeats)
        gpu_flow = gpu_flow_holder["f"]
        print(f"GPU  all_or_nothing : best={gpu_best*1e3:8.1f} ms   avg={gpu_avg*1e3:8.1f} ms")

        # correctness: GPU flow vs CPU flow
        l1 = float(np.abs(gpu_flow - cpu_flow).sum())
        mx = float(np.abs(gpu_flow - cpu_flow).max())
        denom = float(np.abs(cpu_flow).sum()) or 1.0
        print(
            f"\ncorrectness: L1 diff={l1:.3f} ({100*l1/denom:.4f}% of total flow) · "
            f"max abs diff={mx:.3f}"
        )
        speedup = cpu_best / gpu_best if gpu_best > 0 else float("inf")
        verdict = "GPU faster" if speedup > 1 else "CPU faster"
        print(f"speed: {speedup:.2f}x  -> {verdict} (best-of-{args.repeats}, on {net.n_links:,} links)")
    else:
        print("GPU backend NOT available (cudf/cugraph import failed)")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
