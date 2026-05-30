"""P01 data-pipeline tests — network-mocked, fixture-based (no real downloads).

Contracts (from the P01 spec "Test-driven design"):
  * ckan.resolve_resource resolves a resource URL by format/name (mocked HTTP);
  * restrictions.parse(sample_json) -> records with epoch-ms -> datetime and
    geoPolyline -> shapely LineString;
  * weather.parse_filename handles the malformed `weather_2023 6_00.csv` name;
  * bake.write_parquet produces a parquet with the expected columns/dtypes and
    bake.build_catalog + verify round-trip through DuckDB.
"""

from __future__ import annotations

from datetime import datetime, timezone

from torontosim.datapipeline import bake, ckan, restrictions, weather


# --------------------------------------------------------------------------- #
# CKAN (mocked HTTP)
# --------------------------------------------------------------------------- #
def _fake_package_show(_url, params=None, headers=None, timeout=30):
    assert params and params.get("id") == "ttc-routes-and-schedules"
    return {
        "result": {
            "resources": [
                {"id": "uuid-csv", "format": "CSV", "name": "ttc stops csv", "url": "http://x/csv"},
                {"id": "uuid-zip", "format": "ZIP", "name": "TTC Routes and Schedules Data", "url": "http://x/gtfs.zip"},
            ]
        }
    }


def test_ckan_resolve_resource_by_format():
    res = ckan.resolve_resource(
        "ttc-routes-and-schedules", "zip", get_json=_fake_package_show
    )
    assert res["url"] == "http://x/gtfs.zip"
    assert res["id"] == "uuid-zip"


def test_ckan_resolve_resource_by_name_substring():
    res = ckan.resolve_resource(
        "ttc-routes-and-schedules",
        "csv",
        name_contains="stops",
        get_json=_fake_package_show,
    )
    assert res["id"] == "uuid-csv"


def test_ckan_resolve_resource_missing_raises():
    import pytest

    with pytest.raises(LookupError):
        ckan.resolve_resource(
            "ttc-routes-and-schedules", "geojson", get_json=_fake_package_show
        )


def test_ckan_dump_url():
    assert ckan.dump_url("abc-123").endswith("/datastore/dump/abc-123")


# --------------------------------------------------------------------------- #
# Road restrictions (live CART feed shape)
# --------------------------------------------------------------------------- #
SAMPLE_CART = {
    "Closure": [
        {
            "id": "RC-1",
            "road": "Gardiner Expressway",
            "name": "WC closure",
            "roadClass": "Expressway",
            "planned": "1",
            "startTime": 1_780_000_000_000,  # epoch ms
            "endTime": 1_780_010_000_000,
            "type": "CONSTRUCTION",
            "directionsAffected": "Eastbound",
            "maxImpact": "5",
            # geoPolyline as documented: list of [lng, lat] pairs.
            "geoPolyline": [[-79.40, 43.63], [-79.39, 43.64]],
        }
    ]
}


def test_restrictions_parse_epoch_and_geometry():
    recs = restrictions.parse(SAMPLE_CART)
    assert len(recs) == 1
    r = recs[0]
    assert r["id"] == "RC-1"
    assert r["type"] == "CONSTRUCTION"
    # epoch ms -> aware datetime (UTC)
    assert isinstance(r["start_time"], datetime)
    assert r["start_time"] == datetime.fromtimestamp(1_780_000_000, tz=timezone.utc)
    assert r["end_time"] == datetime.fromtimestamp(1_780_010_000, tz=timezone.utc)
    # geoPolyline [lng,lat] -> LineString with (x=lng, y=lat)
    geom = r["geometry"]
    assert geom.geom_type == "LineString"
    assert tuple(geom.coords[0]) == (-79.40, 43.63)


def test_restrictions_parse_accepts_bare_list():
    recs = restrictions.parse(SAMPLE_CART["Closure"])
    assert len(recs) == 1


# --------------------------------------------------------------------------- #
# Weather filename normalization (fix Liron's malformed names)
# --------------------------------------------------------------------------- #
def test_weather_parse_filename_clean():
    assert weather.parse_filename("weather_2020_01.csv") == (2020, 1)


def test_weather_parse_filename_malformed_space():
    # The committed-then-removed bad files: `weather_2023 6_00.csv`.
    assert weather.parse_filename("weather_2023 6_00.csv") == (2023, 6)


def test_weather_canonical_name():
    assert weather.canonical_name(2023, 6) == "weather_2023_06.csv"


# --------------------------------------------------------------------------- #
# Bake → Parquet + DuckDB catalog
# --------------------------------------------------------------------------- #
TMC_SAMPLE = [
    {
        "count_id": 1,
        "count_date": "2022-06-01",
        "location_name": "BLOOR ST / YONGE ST",
        "longitude": -79.385,
        "latitude": 43.670,
        "centreline_id": 13466414,
        "px": 42,
        "start_time": "07:00",
        "end_time": "07:15",
        "n_appr_cars_t": 120,
    },
    {
        "count_id": 2,
        "count_date": "2022-06-01",
        "location_name": "KING ST / BAY ST",
        "longitude": -79.380,
        "latitude": 43.648,
        "centreline_id": 13466500,
        "px": 7,
        "start_time": "08:00",
        "end_time": "08:15",
        "n_appr_cars_t": 88,
    },
]


def test_bake_write_parquet_schema(tmp_path):
    out = tmp_path / "tmc.parquet"
    bake.write_parquet(TMC_SAMPLE, out)
    cols = bake.parquet_columns(out)
    for required in ("centreline_id", "px", "start_time", "longitude", "latitude"):
        assert required in cols
    assert bake.parquet_rowcount(out) == 2


def test_bake_geometry_as_wkt(tmp_path):
    from shapely.geometry import Point

    rows = [
        {"intersection_id": 1, "geometry": Point(-79.38, 43.65)},
        {"intersection_id": 2, "geometry": Point(-79.39, 43.66)},
    ]
    out = tmp_path / "intersections.parquet"
    bake.write_parquet(rows, out, geometry_col="geometry")
    cols = bake.parquet_columns(out)
    assert "geometry_wkt" in cols
    assert "geometry" not in cols  # raw shapely object replaced by WKT


def test_bake_catalog_and_verify(tmp_path):
    pq_dir = tmp_path / "parquet"
    pq_dir.mkdir()
    bake.write_parquet(TMC_SAMPLE, pq_dir / "tmc.parquet")
    db = tmp_path / "catalog.duckdb"
    bake.build_catalog(pq_dir, db)
    # verify() asserts row-count floors via the catalog.
    report = bake.verify(db, floors={"tmc": 2})
    assert report["tmc"]["rows"] == 2
    assert report["tmc"]["ok"] is True
    # A floor above the actual count fails.
    report2 = bake.verify(db, floors={"tmc": 99})
    assert report2["tmc"]["ok"] is False
