"""Normalize raw records -> (Geo)Parquet + a DuckDB catalog (research/01).

Kept deliberately light: tabular data goes to Parquet via pyarrow; geometry is
stored as a ``geometry_wkt`` column (EPSG:4326) rather than pulling in
geopandas. A DuckDB catalog exposes one view per parquet for fast local
queries and row-count verification.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from typing import Any

# Datasets we bake, and their row-count floors for `verify` (research/01 counts).
ROWCOUNT_FLOORS = {
    "centreline": 60_000,
    "intersections": 40_000,
    "tmc": 300_000,
    "signals": 2_000,
    "bridges": 1_500,
}


def _to_wkt(value: Any) -> Any:
    """Shapely geometry -> WKT string; pass through None/str unchanged."""
    if value is None or isinstance(value, str):
        return value
    wkt = getattr(value, "wkt", None)
    return wkt if wkt is not None else str(value)


def _normalize_rows(rows: Sequence[dict], geometry_col: str | None) -> tuple[list[dict], list[str]]:
    """Replace a shapely ``geometry_col`` with ``<col>_wkt``; union the columns."""
    norm: list[dict] = []
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        r = dict(row)
        if geometry_col and geometry_col in r:
            r[f"{geometry_col}_wkt"] = _to_wkt(r.pop(geometry_col))
        norm.append(r)
        for k in r:
            if k not in seen:
                seen.add(k)
                columns.append(k)
    return norm, columns


def write_parquet(rows: Iterable[dict], out_path, *, geometry_col: str | None = None) -> str:
    """Write records to a Parquet file. Geometry (if any) is stored as WKT.

    A consistent schema is enforced across rows by unioning keys and filling
    missing values with ``None``.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = list(rows)
    norm, columns = _normalize_rows(rows, geometry_col)
    table_dict = {col: [r.get(col) for r in norm] for col in columns}
    table = pa.table(table_dict) if columns else pa.table({})

    out_path = str(out_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    # Attach CRS metadata so downstream readers know the WKT geometry frame.
    meta = {b"crs": b"EPSG:4326"} if geometry_col else {}
    if meta:
        table = table.replace_schema_metadata(meta)
    pq.write_table(table, out_path)
    return out_path


def parquet_columns(path) -> list[str]:
    import pyarrow.parquet as pq

    return list(pq.read_schema(str(path)).names)


def parquet_rowcount(path) -> int:
    import pyarrow.parquet as pq

    return pq.ParquetFile(str(path)).metadata.num_rows


def build_catalog(parquet_dir, db_path) -> str:
    """Create a DuckDB DB with one view per ``*.parquet`` in ``parquet_dir``."""
    import duckdb

    parquet_dir = str(parquet_dir)
    db_path = str(db_path)
    con = duckdb.connect(db_path)
    try:
        for fn in sorted(os.listdir(parquet_dir)):
            if not fn.endswith(".parquet"):
                continue
            view = os.path.splitext(fn)[0]
            full = os.path.join(parquet_dir, fn).replace("'", "''")
            con.execute(
                f"CREATE OR REPLACE VIEW {view} AS " f"SELECT * FROM read_parquet('{full}')"
            )
    finally:
        con.close()
    return db_path


def verify(db_path, *, floors: dict[str, int] | None = None) -> dict[str, dict]:
    """Check each view's row count against its floor. Returns a per-view report."""
    import duckdb

    floors = floors or ROWCOUNT_FLOORS
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        views = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        report: dict[str, dict] = {}
        for name, floor in floors.items():
            if name not in views:
                report[name] = {"rows": 0, "floor": floor, "ok": False, "missing": True}
                continue
            rows = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            report[name] = {"rows": rows, "floor": floor, "ok": rows >= floor}
        return report
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Per-dataset normalizers: raw CKAN CSV/GeoJSON -> normalized rows -> Parquet.
#
# Each ``bake_<dataset>`` reads the raw pull (the file ``fetch`` wrote to
# ``data/raw/<name>.<ext>``), normalizes to the canonical columns + join keys
# from research/01, converts any geometry to WKT (EPSG:4326), and writes one
# parquet. The readers parse GeoJSON datastore variants without geopandas.
# --------------------------------------------------------------------------- #

# Datasets we know how to fetch+bake, and the raw file extension `fetch` writes.
RAW_EXT = {
    "centreline": "csv",
    "intersections": "geojson",
    "tmc": "csv",
    "signals": "csv",
    "bridges": "geojson",
    "zones": "geojson",
}


def _coerce_int(value: Any):
    """Best-effort int (handles ``"42"``, ``"42.0"``, floats); ``None`` on fail."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_geometry(value: Any):
    """Raw geometry cell (GeoJSON string / WKT / GeoJSON dict) -> shapely geom."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        # Already a GeoJSON mapping or shapely geometry.
        if isinstance(value, dict):
            from shapely.geometry import shape

            try:
                return shape(value)
            except Exception:  # noqa: BLE001
                return None
        return value
    s = value.strip()
    try:
        if s.startswith("{"):
            import json

            from shapely.geometry import shape

            return shape(json.loads(s))
        from shapely import wkt

        return wkt.loads(s)
    except Exception:  # noqa: BLE001
        return None


def read_raw_records(path) -> list[dict]:
    """Read a raw CKAN pull (``.csv`` / ``.geojson`` / ``.json``) to record dicts.

    GeoJSON features are flattened to ``properties`` + a shapely ``geometry``;
    CSV rows keep their string cells (a ``geometry`` column, if present, is
    parsed to shapely). Type coercion is the per-dataset normalizer's job.
    """
    ext = os.path.splitext(str(path))[1].lower()
    if ext in (".geojson", ".json"):
        return _read_geojson(path)
    if ext == ".csv":
        return _read_csv(path)
    raise ValueError(f"unsupported raw format {ext!r} for {path}")


def _read_geojson(path) -> list[dict]:
    import json

    with open(path) as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        feats = data.get("features", [])
    elif isinstance(data, list):
        feats = data
    else:
        feats = []
    out: list[dict] = []
    for f in feats:
        props = dict(f.get("properties") or {})
        props["geometry"] = _parse_geometry(f.get("geometry"))
        out.append(props)
    return out


def _read_csv(path) -> list[dict]:
    import csv

    out: list[dict] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            r = dict(row)
            if "geometry" in r:
                r["geometry"] = _parse_geometry(r["geometry"])
            out.append(r)
    return out


def _normalize(
    records: Iterable[dict],
    *,
    int_cols: Sequence[str] = (),
    float_cols: Sequence[str] = (),
    int_suffixes: Sequence[str] = (),
) -> list[dict]:
    """Coerce declared columns to int/float; pass everything else through.

    ``int_suffixes`` coerces any column whose name ends with one of them (used
    for the TMC per-movement count columns, e.g. ``n_appr_cars_t``).
    """
    int_set = set(int_cols)
    float_set = set(float_cols)
    rows: list[dict] = []
    for rec in records:
        r = dict(rec)
        r.pop("_id", None)  # CKAN datastore row id — not meaningful downstream.
        for k in list(r):
            if k in int_set or (int_suffixes and k.endswith(tuple(int_suffixes))):
                r[k] = _coerce_int(r[k])
            elif k in float_set:
                r[k] = _coerce_float(r[k])
        rows.append(r)
    return rows


def bake_centreline(src, out_path) -> str:
    rows = _normalize(
        read_raw_records(src),
        int_cols=(
            "CENTRELINE_ID",
            "FROM_INTERSECTION_ID",
            "TO_INTERSECTION_ID",
            "ONEWAY_DIR_CODE",
            "FEATURE_CODE",
        ),
    )
    return write_parquet(rows, out_path, geometry_col="geometry")


def bake_intersections(src, out_path) -> str:
    rows = _normalize(
        read_raw_records(src),
        int_cols=("INTERSECTION_ID", "ELEVATION", "NUMBER_OF_ELEVATIONS"),
    )
    return write_parquet(rows, out_path, geometry_col="geometry")


def bake_tmc(src, out_path) -> str:
    rows = _normalize(
        read_raw_records(src),
        int_cols=("count_id", "centreline_id", "px", "centreline_type"),
        float_cols=("longitude", "latitude"),
        int_suffixes=("_r", "_t", "_l", "_peds", "_bike"),
    )
    return write_parquet(rows, out_path)


def bake_signals(src, out_path) -> str:
    rows = _normalize(
        read_raw_records(src),
        int_cols=("PX", "TRANSIT_PREEMPT"),
        float_cols=("PEDWALKSPEED",),
    )
    return write_parquet(rows, out_path, geometry_col="geometry")


def bake_bridges(src, out_path) -> str:
    rows = _normalize(
        read_raw_records(src),
        int_cols=("WARD_NO", "CENTRELINE_ID"),
        float_cols=("VERT_CLEAR",),
    )
    return write_parquet(rows, out_path, geometry_col="geometry")


def bake_zones(src, out_path) -> str:
    rows = _normalize(read_raw_records(src))
    return write_parquet(rows, out_path, geometry_col="geometry")


BAKERS = {
    "centreline": bake_centreline,
    "intersections": bake_intersections,
    "tmc": bake_tmc,
    "signals": bake_signals,
    "bridges": bake_bridges,
    "zones": bake_zones,
}


def bake_all(
    raw_dir,
    parquet_dir,
    *,
    db_path=None,
    manifest_path=None,
    fetched_at: str = "",
) -> dict[str, dict]:
    """Bake every raw dataset found in ``raw_dir`` -> parquet + catalog + manifest.

    Returns a per-dataset report ``{name: {rows, parquet, sha256}}``. Datasets
    whose raw file is absent are skipped (the bake stays partial-friendly so a
    ``--only`` fetch can be baked alone).
    """
    from .manifest import ATTRIBUTION, Manifest, ManifestEntry, sha256_file

    raw_dir = str(raw_dir)
    parquet_dir = str(parquet_dir)
    os.makedirs(parquet_dir, exist_ok=True)

    report: dict[str, dict] = {}
    manifest = Manifest()
    for name, baker in BAKERS.items():
        ext = RAW_EXT.get(name, "csv")
        raw_path = os.path.join(raw_dir, f"{name}.{ext}")
        if not os.path.exists(raw_path):
            continue
        out = os.path.join(parquet_dir, f"{name}.parquet")
        baker(raw_path, out)
        rows = parquet_rowcount(out)
        sha = sha256_file(raw_path)
        report[name] = {"rows": rows, "parquet": out, "sha256": sha}
        manifest.add(
            ManifestEntry(
                dataset=name,
                source_url=f"data/raw/{name}.{ext}",
                resource_uuid=None,
                fetched_at=fetched_at,
                sha256=sha,
                license=ATTRIBUTION["toronto"],
                path=out,
                rows=rows,
            )
        )

    if db_path is not None:
        build_catalog(parquet_dir, db_path)
    if manifest_path is not None:
        manifest.write(manifest_path)
    return report
