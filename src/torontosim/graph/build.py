"""Graph builder CLI (P02): ``python -m torontosim.graph.build --source …``.

    --source osmnx       Liron's OSMnx download path (baseline; needs network).
    --source centreline  Build from the P01-baked Centreline parquet store.

Both write a canonical-schema graph JSON via ``routing.export_graph_json`` and
print a class histogram. GPU/citywide scaling is a P11 concern.
"""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")


def _data_dir(arg: str | None) -> str:
    return os.path.abspath(arg or os.environ.get("TS_DATA_DIR", DEFAULT_DATA))


def _histogram(graph) -> dict[str, int]:
    hist: dict[str, int] = {}
    for _u, _v, d in graph.edges(data=True):
        rc = d.get("road_class", "unknown")
        hist[rc] = hist.get(rc, 0) + 1
    return hist


def build_centreline(data_dir: str, *, calibrate: bool = True):
    from . import calibrate_capacity, centreline_loader, schema

    pq_dir = os.path.join(data_dir, "parquet")
    graph = centreline_loader.load_from_parquet(pq_dir)
    if calibrate:
        import pyarrow.parquet as pq

        tmc_path = os.path.join(pq_dir, "tmc.parquet")
        if os.path.exists(tmc_path):
            n = calibrate_capacity.calibrate(graph, pq.read_table(tmc_path).to_pylist())
            print(f"[build] calibrated {n} edges against TMC peaks")
    schema.validate_graph(graph)
    return graph


def build_osmnx(**kwargs):
    from . import schema
    from .build_graph import download_graph, enrich_graph

    graph = download_graph(**kwargs)
    enrich_graph(graph)
    schema.ensure_confidence(graph, label="inferred")
    schema.validate_graph(graph)
    return graph


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="torontosim.graph.build")
    p.add_argument("--source", choices=["osmnx", "centreline"], default="centreline")
    p.add_argument("--data-dir", default=None)
    p.add_argument("--out", default=None, help="output graph JSON path")
    p.add_argument("--no-calibrate", action="store_true")
    args = p.parse_args(argv)

    data_dir = _data_dir(args.data_dir)
    try:
        if args.source == "centreline":
            graph = build_centreline(data_dir, calibrate=not args.no_calibrate)
        else:
            graph = build_osmnx()
    except FileNotFoundError as exc:
        print(f"[build] {exc}", file=sys.stderr)
        return 1

    from .routing import export_graph_json, summarize_graph

    summarize_graph(graph)
    print("[build] class histogram:", _histogram(graph))
    out = args.out or os.path.join(data_dir, "graph", f"toronto_{args.source}_graph.json")
    export_graph_json(graph, out)
    print(
        f"[build] wrote {out} ({graph.number_of_nodes()} nodes / {graph.number_of_edges()} edges)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
