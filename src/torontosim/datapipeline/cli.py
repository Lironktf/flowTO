"""Data-pipeline CLI: ``python -m torontosim.datapipeline {fetch,bake,verify}``.

This is the one-command ingest the judges run. ``fetch`` downloads raw sources
(network), ``bake`` normalizes the raw cache to Parquet + a DuckDB catalog
(offline-repeatable), ``verify`` checks row-count floors via the catalog.

Network fetches are intentionally not unit-tested here (mocked in
``tests/test_datapipeline.py``); run ``fetch`` before the event or on the Spark.
"""

from __future__ import annotations

import argparse
import os
import sys

# Catalog of CKAN datasets to fetch (research/01). Resolve-by-name on fetch.
CKAN_DATASETS = {
    "centreline": ("toronto-centreline-tcl", "csv"),
    "intersections": ("intersection-file-city-of-toronto", "geojson"),
    "tmc": ("traffic-volumes-at-intersections-for-all-modes", "csv"),
    "signals": ("traffic-signals-tabular", "csv"),
    "bridges": ("bridge-structure", "geojson"),
    "zones": ("neighbourhoods", "geojson"),
}

DEFAULT_DATA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data"
)


def _resolve_data_dir(arg: str | None) -> str:
    return os.path.abspath(arg or os.environ.get("TS_DATA_DIR", DEFAULT_DATA))


def _split_only(only: str | None) -> set[str] | None:
    if not only:
        return None
    return {s.strip() for s in only.split(",") if s.strip()}


def cmd_fetch(args) -> int:
    from . import ckan, gtfs, restrictions
    from .manifest import ATTRIBUTION

    data_dir = _resolve_data_dir(args.data_dir)
    raw_dir = os.path.join(data_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    only = _split_only(args.only)
    print("[fetch] attribution:", ATTRIBUTION["toronto"])

    for name, (pkg, fmt) in CKAN_DATASETS.items():
        if only and name not in only:
            continue
        try:
            res = ckan.resolve_resource(pkg, fmt)
            url = res.get("url") or ckan.dump_url(res["id"])
            dest = os.path.join(raw_dir, f"{name}.{fmt}")
            print(f"[fetch] {name}: {url}")
            ckan.download_file(url, dest)
        except Exception as exc:  # noqa: BLE001 — keep fetching other datasets.
            print(f"[fetch] {name} FAILED: {exc!r}", file=sys.stderr)

    if not only or "restrictions" in only:
        try:
            recs = restrictions.fetch()
            print(f"[fetch] restrictions: {len(recs)} live closures")
        except Exception as exc:  # noqa: BLE001
            print(f"[fetch] restrictions FAILED: {exc!r}", file=sys.stderr)

    if not only or only & set(gtfs.list_feeds()):
        for key in gtfs.list_feeds():
            if only and key not in only:
                continue
            try:
                meta = gtfs.fetch_feed(key, raw_dir, date_tag=args.date_tag)
                print(f"[fetch] gtfs/{key}: {meta['path']}")
            except Exception as exc:  # noqa: BLE001
                print(f"[fetch] gtfs/{key} FAILED: {exc!r}", file=sys.stderr)
    return 0


def cmd_bake(args) -> int:
    """Normalize the raw cache to Parquet + DuckDB catalog (offline)."""
    from . import bake

    data_dir = _resolve_data_dir(args.data_dir)
    pq_dir = os.path.join(data_dir, "parquet")
    os.makedirs(pq_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "catalog.duckdb")
    # Bake is dataset-specific; the CKAN CSV/GeoJSON readers land per-dataset in
    # follow-up work. Here we (re)build the catalog over whatever parquet exists.
    bake.build_catalog(pq_dir, db_path)
    print(f"[bake] catalog -> {db_path}")
    return 0


def cmd_verify(args) -> int:
    from . import bake

    data_dir = _resolve_data_dir(args.data_dir)
    db_path = os.path.join(data_dir, "catalog.duckdb")
    if not os.path.exists(db_path):
        print(f"[verify] no catalog at {db_path}; run `bake` first", file=sys.stderr)
        return 1
    report = bake.verify(db_path)
    ok = True
    for name, r in sorted(report.items()):
        flag = "ok" if r["ok"] else "FAIL"
        ok = ok and r["ok"]
        print(f"[verify] {name:14} rows={r['rows']:>8} floor={r['floor']:>8} {flag}")
    return 0 if ok else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="torontosim.datapipeline")
    p.add_argument("--data-dir", default=None, help="override data/ root")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="download raw sources")
    pf.add_argument("--only", default=None, help="comma list, e.g. ttc,tmc,centreline")
    pf.add_argument("--date-tag", default="latest", help="cache tag for GTFS zips")
    pf.set_defaults(func=cmd_fetch)

    pb = sub.add_parser("bake", help="normalize raw -> parquet + duckdb catalog")
    pb.set_defaults(func=cmd_bake)

    pv = sub.add_parser("verify", help="row-count floors via the catalog")
    pv.set_defaults(func=cmd_verify)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
