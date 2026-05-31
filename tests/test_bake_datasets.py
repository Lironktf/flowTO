"""W1 — raw→Parquet bake normalizers (network-mocked, fixture-based).

The per-dataset bakers turn the raw CKAN CSV/GeoJSON pulls (tiny committed
fixtures under ``tests/fixtures/raw/``) into normalized Parquet with the
canonical columns + join keys from ``research/01``. Geometry is stored as WKT
(EPSG:4326) so downstream readers stay geopandas-free. Real fetch+bake is
exercised separately under ``@pytest.mark.network`` (Spark/pre-event).
"""

from __future__ import annotations

import os

import pyarrow as pa
import pyarrow.parquet as pq

from torontosim.datapipeline import bake

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "raw")


def _schema(path):
    return pq.read_schema(str(path))


def _is_integer(schema: pa.Schema, name: str) -> bool:
    return pa.types.is_integer(schema.field(name).type)


# --------------------------------------------------------------------------- #
# Centreline (CSV with GeoJSON-string geometry)
# --------------------------------------------------------------------------- #
def test_bake_centreline_schema(tmp_path):
    out = tmp_path / "centreline.parquet"
    bake.bake_centreline(os.path.join(FIX, "centreline.csv"), out)
    sch = _schema(out)
    for col in (
        "CENTRELINE_ID",
        "LINEAR_NAME_FULL",
        "FROM_INTERSECTION_ID",
        "TO_INTERSECTION_ID",
        "ONEWAY_DIR_CODE",
        "FEATURE_CODE_DESC",
        "geometry_wkt",
    ):
        assert col in sch.names, col
    # Join keys / direction code must be integer-typed for the loader.
    assert _is_integer(sch, "CENTRELINE_ID")
    assert _is_integer(sch, "ONEWAY_DIR_CODE")
    assert _is_integer(sch, "FROM_INTERSECTION_ID")
    assert bake.parquet_rowcount(out) == 4  # river kept (loader filters, not bake)
    # Geometry round-trips to WKT.
    rows = pq.read_table(out).to_pylist()
    assert rows[0]["geometry_wkt"].startswith("LINESTRING")


# --------------------------------------------------------------------------- #
# Intersections (GeoJSON points; multi-level dupes preserved in the raw bake)
# --------------------------------------------------------------------------- #
def test_bake_intersections_schema(tmp_path):
    out = tmp_path / "intersections.parquet"
    bake.bake_intersections(os.path.join(FIX, "intersections.geojson"), out)
    sch = _schema(out)
    for col in ("INTERSECTION_ID", "INTERSECTION_DESC", "geometry_wkt"):
        assert col in sch.names, col
    assert _is_integer(sch, "INTERSECTION_ID")
    rows = pq.read_table(out).to_pylist()
    assert rows[0]["geometry_wkt"].startswith("POINT")
    assert bake.parquet_rowcount(out) == 4


# --------------------------------------------------------------------------- #
# TMC (CSV, no geometry; movement columns preserved + numeric)
# --------------------------------------------------------------------------- #
def test_bake_tmc_schema(tmp_path):
    out = tmp_path / "tmc.parquet"
    bake.bake_tmc(os.path.join(FIX, "tmc.csv"), out)
    sch = _schema(out)
    for col in (
        "centreline_id",
        "px",
        "start_time",
        "end_time",
        "longitude",
        "latitude",
        "n_appr_cars_t",
    ):
        assert col in sch.names, col
    assert _is_integer(sch, "centreline_id")
    assert _is_integer(sch, "px")
    assert _is_integer(sch, "n_appr_cars_t")
    assert pa.types.is_floating(sch.field("longitude").type)
    # start_time stays a string (ISO timestamp); never coerced to a number.
    assert pa.types.is_string(sch.field("start_time").type)
    assert bake.parquet_rowcount(out) == 3


# --------------------------------------------------------------------------- #
# Signals / Bridges / Zones (geometry → WKT)
# --------------------------------------------------------------------------- #
def test_bake_signals_schema(tmp_path):
    out = tmp_path / "signals.parquet"
    bake.bake_signals(os.path.join(FIX, "signals.csv"), out)
    sch = _schema(out)
    for col in ("PX", "MAIN_STREET", "CONTROL_MODE", "geometry_wkt"):
        assert col in sch.names, col
    assert _is_integer(sch, "PX")


def test_bake_bridges_schema(tmp_path):
    out = tmp_path / "bridges.parquet"
    bake.bake_bridges(os.path.join(FIX, "bridges.geojson"), out)
    sch = _schema(out)
    for col in ("STRUCT_ID", "VERT_CLEAR", "CENTRELINE_ID", "geometry_wkt"):
        assert col in sch.names, col
    assert pa.types.is_floating(sch.field("VERT_CLEAR").type)
    rows = pq.read_table(out).to_pylist()
    assert rows[0]["geometry_wkt"].startswith("POINT")


def test_bake_zones_schema(tmp_path):
    out = tmp_path / "zones.parquet"
    bake.bake_zones(os.path.join(FIX, "zones.geojson"), out)
    sch = _schema(out)
    for col in ("AREA_SHORT_CODE", "AREA_NAME", "geometry_wkt"):
        assert col in sch.names, col
    rows = pq.read_table(out).to_pylist()
    assert rows[0]["geometry_wkt"].startswith("POLYGON")


def test_bake_detects_csv_content_in_geojson_file(tmp_path):
    """Live-portal quirk: the CKAN datastore serves CSV from a `.geojson`
    resource (the /datastore/dump URL is always CSV). bake must sniff content,
    not trust the extension, and still parse the geometry column.
    """
    src = tmp_path / "intersections.geojson"  # .geojson name, CSV body
    src.write_text(
        "INTERSECTION_ID,INTERSECTION_DESC,geometry\n"
        '100,Yonge / King,"{""type"":""Point"",""coordinates"":[-79.38,43.65]}"\n'
    )
    out = tmp_path / "intersections.parquet"
    bake.bake_intersections(src, out)
    rows = pq.read_table(out).to_pylist()
    assert rows[0]["INTERSECTION_ID"] == 100
    assert rows[0]["geometry_wkt"].startswith("POINT")


# --------------------------------------------------------------------------- #
# Full bake_all over a raw dir → catalog + manifest with sha256/license
# --------------------------------------------------------------------------- #
def test_bake_all_catalog_and_manifest(tmp_path):
    pq_dir = tmp_path / "parquet"
    db = tmp_path / "catalog.duckdb"
    manifest_path = tmp_path / "manifest.json"
    report = bake.bake_all(FIX, pq_dir, db_path=db, manifest_path=manifest_path)

    # All six datasets produced a parquet.
    for name in ("centreline", "intersections", "tmc", "signals", "bridges", "zones"):
        assert (pq_dir / f"{name}.parquet").exists(), name
        assert name in report

    # Catalog verifies against low floors.
    vr = bake.verify(db, floors={"centreline": 4, "tmc": 3, "intersections": 4})
    assert vr["centreline"]["ok"] and vr["tmc"]["ok"]

    # Manifest carries sha256 + license per dataset.
    from torontosim.datapipeline.manifest import ATTRIBUTION, Manifest

    m = Manifest.load(manifest_path)
    by_ds = {e.dataset: e for e in m.entries}
    assert "centreline" in by_ds
    assert len(by_ds["centreline"].sha256) == 64
    assert by_ds["centreline"].license == ATTRIBUTION["toronto"]


def test_cmd_bake_cli_over_raw_dir(tmp_path):
    """`python -m torontosim.datapipeline bake` bakes the raw cache + catalog."""
    import shutil

    from torontosim.datapipeline.cli import main

    data_dir = tmp_path / "data"
    raw = data_dir / "raw"
    raw.mkdir(parents=True)
    for fn in (
        "centreline.csv",
        "intersections.geojson",
        "tmc.csv",
        "signals.csv",
        "bridges.geojson",
        "zones.geojson",
    ):
        shutil.copy(os.path.join(FIX, fn), raw / fn)

    assert main(["--data-dir", str(data_dir), "bake"]) == 0
    assert (data_dir / "parquet" / "centreline.parquet").exists()
    assert (data_dir / "catalog.duckdb").exists()
    assert (data_dir / "manifest.json").exists()
    # verify subcommand passes with floors satisfied by the fixtures.
    assert bake.parquet_rowcount(data_dir / "parquet" / "tmc.parquet") == 3
