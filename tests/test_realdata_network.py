"""Real fetch+bake against live City of Toronto + Metrolinx sources.

All ``@pytest.mark.network`` → **skipped in CI**; run on the Spark / pre-event
(``scripts/spark/fetch_and_bake.sh``) where the disk + network are available.
These prove the W1–W4 pipeline against the real datasets (the fixture tests are
the hermetic contract; these are the end-to-end acceptance).
"""

from __future__ import annotations

import os

import pytest

from torontosim.datapipeline import bake
from torontosim.datapipeline.cli import main as dp_main

pytestmark = pytest.mark.network


def test_real_fetch_bake_centreline_tmc(tmp_path):
    """fetch → bake → verify yields the real store; centreline ≥ 60k segments."""
    data_dir = str(tmp_path / "data")
    rc = dp_main(["--data-dir", data_dir, "fetch", "--only", "centreline,intersections,tmc"])
    assert rc == 0
    assert dp_main(["--data-dir", data_dir, "bake"]) == 0

    report = bake.verify(os.path.join(data_dir, "catalog.duckdb"))
    assert report["centreline"]["rows"] >= 60_000, report["centreline"]
    assert report["intersections"]["rows"] >= 40_000, report["intersections"]
    assert report["tmc"]["rows"] >= 300_000, report["tmc"]


def test_real_centreline_graph_builds_and_validates(tmp_path):
    """The real baked store builds a canonical, schema-valid Centreline graph."""
    data_dir = str(tmp_path / "data")
    assert dp_main(["--data-dir", data_dir, "fetch", "--only", "centreline,intersections,tmc"]) == 0
    assert dp_main(["--data-dir", data_dir, "bake"]) == 0

    from torontosim.graph import schema
    from torontosim.graph.centreline_loader import load_from_parquet

    graph = load_from_parquet(os.path.join(data_dir, "parquet"))
    assert graph.number_of_edges() > 10_000
    schema.validate_graph(graph)


def test_real_ttc_gtfs_feed(tmp_path):
    """Real TTC GTFS reads into mode-tagged routes + invariant trajectories."""
    from torontosim.datapipeline import gtfs as gtfs_fetch
    from torontosim.transit import gtfs_reader

    raw = str(tmp_path / "raw")
    os.makedirs(raw, exist_ok=True)
    meta = gtfs_fetch.fetch_feed("ttc", raw, date_tag="latest")

    feed = gtfs_reader.build_feed(meta["path"], agency="ttc")
    assert len(feed["routes"]) > 100  # TTC runs hundreds of routes
    assert feed["trajectories"]
    for t in feed["trajectories"][:500]:
        ts = t["timestamps"]
        assert all(b >= a for a, b in zip(ts, ts[1:]))  # monotonic, no wrap
