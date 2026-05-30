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

# Catalog of CKAN datasets to fetch (research/01): name -> (package, format,
# name_contains). ``name_contains`` disambiguates packages with many same-format
# resources — e.g. the TMC package ships a 346k-row raw decade file AND a 6k-row
# summary; without it, first-by-format can grab the wrong one. ``None`` = take
# the first resource of that format.
CKAN_DATASETS = {
    "centreline": ("toronto-centreline-tcl", "csv", None),
    "intersections": ("intersection-file-city-of-toronto", "geojson", None),
    "tmc": ("traffic-volumes-at-intersections-for-all-modes", "csv", "raw_data_2020_2029"),
    "signals": ("traffic-signals-tabular", "csv", None),
    "bridges": ("bridge-structure", "geojson", None),
    "zones": ("neighbourhoods", "geojson", None),
}

DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")


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

    for name, (pkg, fmt, name_contains) in CKAN_DATASETS.items():
        if only and name not in only:
            continue
        try:
            res = ckan.resolve_resource(pkg, fmt, name_contains=name_contains)
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
    """Normalize the raw cache to Parquet + DuckDB catalog + manifest (offline)."""
    from . import bake

    data_dir = _resolve_data_dir(args.data_dir)
    raw_dir = os.path.join(data_dir, "raw")
    pq_dir = os.path.join(data_dir, "parquet")
    os.makedirs(pq_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "catalog.duckdb")
    manifest_path = os.path.join(data_dir, "manifest.json")

    # Per-dataset CKAN CSV/GeoJSON normalizers -> parquet; then build the catalog
    # + lineage manifest over whatever was baked.
    report = bake.bake_all(raw_dir, pq_dir, db_path=db_path, manifest_path=manifest_path)
    for name, r in sorted(report.items()):
        print(f"[bake] {name:14} rows={r['rows']:>8} -> {r['parquet']}")
    if not report:
        print(f"[bake] no raw datasets under {raw_dir}; run `fetch` first", file=sys.stderr)
    print(f"[bake] catalog -> {db_path}")
    print(f"[bake] manifest -> {manifest_path}")

    # Bake fetched GTFS zips (raw/gtfs_{agency}_{date}.zip) -> real transit feeds
    # cached at data/transit/{agency}_{date}.json for the overlay.
    _bake_transit(raw_dir, data_dir)
    return 0


def _bake_transit(raw_dir: str, data_dir: str) -> None:
    """Cache each fetched GTFS zip to data/transit/{agency}_{date}.json."""
    import glob

    from ..transit import gtfs_reader

    for zpath in sorted(glob.glob(os.path.join(raw_dir, "gtfs_*.zip"))):
        stem = os.path.splitext(os.path.basename(zpath))[0]  # gtfs_<agency>_<date>
        parts = stem.split("_", 2)
        if len(parts) < 3:
            continue
        _, agency, date = parts
        try:
            out = gtfs_reader.build_feed_cache(zpath, agency=agency, date=date, data_dir=data_dir)
            print(f"[bake] transit/{agency}: {out}")
        except Exception as exc:  # noqa: BLE001 — a bad feed shouldn't fail the bake.
            print(f"[bake] transit/{agency} FAILED: {exc!r}", file=sys.stderr)


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
