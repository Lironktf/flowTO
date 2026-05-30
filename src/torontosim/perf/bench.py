"""Benchmark CLI (P11): full-city vs blast-radius recompute latency.

Runs a fixed closure scenario and times ``recompute=full`` vs
``recompute=blast``, plus the affected-subgraph fraction — the headline perf
table. Reproducible run-to-run (sim determinism from P04). Writes
``data/bench/results.json`` + a Markdown table.
"""

from __future__ import annotations

import json
import os

from .timing import get_timings, reset_timings, timer

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BENCH_DIR = os.path.join(_REPO_ROOT, "data", "bench")


def _default_state():  # pragma: no cover - heavy/full-graph path
    from ..api._bootstrap import load_default_state

    return load_default_state(max_pairs=400)


def benchmark(state=None, *, close_edge_id: str | None = None) -> dict:
    """Time full vs blast recompute for a single closure. Returns a result dict."""
    from ..simulation.simulate_traffic import simulate_scenario

    if state is None:
        state = _default_state()
    reset_timings()

    # Pick an edge to close (the first congested one) if not supplied.
    if close_edge_id is None:
        base = state.baseline(congestion_model="bpr")
        ranked = sorted(
            (
                (d.get("edge_id"), d.get("pressure", 0.0))
                for _u, _v, d in base["graph"].edges(data=True)
                if d.get("status") != "closed" and isinstance(d.get("pressure"), (int, float))
            ),
            key=lambda r: (-(r[1] or 0.0), str(r[0])),
        )
        close_edge_id = ranked[0][0] if ranked else state.edge_ids[0]

    ops = [{"op": "close_edge", "edge_id": close_edge_id}]

    with timer("recompute_full"):
        full = simulate_scenario(
            state.graph,
            state.od_matrix,
            ops,
            weather=state.weather,
            time_context=state.time_context,
            congestion_model="bpr",
            recompute="full",
        )
    with timer("recompute_blast"):
        blast = simulate_scenario(
            state.graph,
            state.od_matrix,
            ops,
            weather=state.weather,
            time_context=state.time_context,
            congestion_model="bpr",
            recompute="blast",
        )

    timings = {t["label"]: t["ms"] for t in get_timings()}
    blast_stats = blast.get("blast_stats", {})
    return {
        "closed_edge": close_edge_id,
        "n_edges": len(state.edge_ids),
        "recompute_full_ms": timings.get("recompute_full"),
        "recompute_blast_ms": timings.get("recompute_blast"),
        "speedup": round(
            (timings.get("recompute_full") or 0) / (timings.get("recompute_blast") or 1), 2
        ),
        "affected_subgraph_fraction": blast_stats.get("node_fraction"),
        "affected_edges": blast_stats.get("subgraph_links"),
        "full_summary": full["summary"],
        "blast_summary": blast["summary"],
    }


def to_markdown(result: dict) -> str:
    return (
        "# Recompute benchmark — full city vs blast-radius\n\n"
        f"- Graph: {result['n_edges']:,} edges · closed edge `{result['closed_edge']}`\n\n"
        "| Mode | Latency (ms) | Affected subgraph |\n"
        "|---|---|---|\n"
        f"| Full recompute | {result['recompute_full_ms']} | 100% |\n"
        f"| Blast-radius | {result['recompute_blast_ms']} | "
        f"{(result.get('affected_subgraph_fraction') or 0) * 100:.1f}% "
        f"({result.get('affected_edges')} edges) |\n\n"
        f"**Speedup: {result['speedup']}×** (blast-radius vs full).\n"
    )


def main(argv=None):  # pragma: no cover - CLI
    import argparse

    argparse.ArgumentParser(prog="torontosim.perf.bench").parse_args(argv)
    result = benchmark()
    os.makedirs(BENCH_DIR, exist_ok=True)
    with open(os.path.join(BENCH_DIR, "results.json"), "w") as fh:
        json.dump(result, fh, indent=2)
    md = to_markdown(result)
    with open(os.path.join(BENCH_DIR, "results.md"), "w") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
