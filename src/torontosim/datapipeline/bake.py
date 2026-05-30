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


def _normalize_rows(
    rows: Sequence[dict], geometry_col: str | None
) -> tuple[list[dict], list[str]]:
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
                f"CREATE OR REPLACE VIEW {view} AS "
                f"SELECT * FROM read_parquet('{full}')"
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
