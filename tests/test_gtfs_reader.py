"""W4 — real GTFS-zip reader → routes + trajectories, with overlay invariants.

Reads the committed tiny TTC-shaped feed (a directory fixture; the reader also
accepts a zip) and asserts the same invariants the demo set guarantees hold on
real data: mode-tagged route LineStrings, monotonic seconds-since-midnight, an
after-midnight trip that does **not** wrap past 86400, and mid-trip positions
that lie on the path. Also covers the cache + API fallback wiring.
"""

from __future__ import annotations

import os
import zipfile

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app
from torontosim.transit import gtfs_reader
from torontosim.transit.trajectories import interpolate_position

FEED = os.path.join(os.path.dirname(__file__), "fixtures", "gtfs", "ttc")


def _zip_of_fixture(tmp_path):
    zpath = tmp_path / "ttc_gtfs.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for fn in os.listdir(FEED):
            zf.write(os.path.join(FEED, fn), arcname=fn)
    return zpath


# --------------------------------------------------------------------------- #
# Route geometry
# --------------------------------------------------------------------------- #
def test_route_lines_tag_mode_from_shapes():
    routes = gtfs_reader.route_lines(FEED, agency="ttc")
    by_id = {r["route_id"]: r for r in routes}
    assert set(by_id) == {"509", "7"}
    assert by_id["509"]["mode"] == "streetcar"  # route_type 0
    assert by_id["7"]["mode"] == "bus"  # route_type 3
    # 509 geometry came from shapes.txt (5 points), not the 3 stops.
    assert len(by_id["509"]["path"]) == 5
    assert all(len(p) == 2 for p in by_id["509"]["path"])


def test_route_lines_reads_from_zip(tmp_path):
    routes = gtfs_reader.route_lines(_zip_of_fixture(tmp_path), agency="ttc")
    assert {r["route_id"] for r in routes} == {"509", "7"}


# --------------------------------------------------------------------------- #
# Trajectories — monotonic, no wrap, on-shape
# --------------------------------------------------------------------------- #
def test_trip_trajectories_invariants():
    trajs = gtfs_reader.trip_trajectories(FEED, agency="ttc")
    by_trip = {t["trip_id"]: t for t in trajs}
    assert {"509_A", "509_LATE", "7_A"} <= set(by_trip)

    for t in trajs:
        ts = t["timestamps"]
        # Monotonic non-decreasing seconds-since-midnight.
        assert all(b >= a for a, b in zip(ts, ts[1:]))
        assert len(t["path"]) == len(ts) >= 2

    # After-midnight trip exceeds 86400 and does NOT wrap.
    late = by_trip["509_LATE"]["timestamps"]
    assert late[0] == 25 * 3600  # 90000
    assert max(late) > 86400

    # Mid-trip position lies on the 509_A path between its first two stops.
    a = by_trip["509_A"]
    pos = interpolate_position(a, a["timestamps"][0] + 60)
    assert pos is not None
    lngs = [p[0] for p in a["path"]]
    assert min(lngs) <= pos[0] <= max(lngs)


# --------------------------------------------------------------------------- #
# Cache + API fallback
# --------------------------------------------------------------------------- #
def test_build_and_load_cache(tmp_path):
    data_dir = tmp_path / "data"
    out = gtfs_reader.build_feed_cache(
        FEED, agency="ttc", date="2026-06-12", data_dir=str(data_dir)
    )
    assert os.path.exists(out)

    exact = gtfs_reader.load_cached_feed("ttc", "2026-06-12", str(data_dir))
    assert exact and len(exact["routes"]) == 2
    # Unknown date falls back to the latest cached feed for the agency.
    fallback = gtfs_reader.load_cached_feed("ttc", "9999-01-01", str(data_dir))
    assert fallback and len(fallback["trajectories"]) >= 3
    # Unknown agency → no real feed.
    assert gtfs_reader.load_cached_feed("go", "2026-06-12", str(data_dir)) is None


def test_api_serves_real_feed_when_cached(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    gtfs_reader.build_feed_cache(FEED, agency="ttc", date="latest", data_dir=str(data_dir))
    monkeypatch.setenv("TS_DATA_DIR", str(data_dir))

    client = TestClient(create_app(_small_state()))
    routes = client.get("/transit/routes?agencies=ttc").json()["routes"]
    # Real feed carries route 7 (the demo set is only 509/511).
    assert {r["route_id"] for r in routes} == {"509", "7"}
    trajs = client.get("/transit/trajectories?agencies=ttc").json()["trajectories"]
    assert any(t["trip_id"] == "509_LATE" for t in trajs)


def test_api_falls_back_to_demo_without_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TS_DATA_DIR", str(tmp_path / "empty"))
    client = TestClient(create_app(_small_state()))
    routes = client.get("/transit/routes?agencies=ttc").json()["routes"]
    # No cache → hand-authored demo set (509 / 511).
    assert {r["route_id"] for r in routes} == {"509", "511"}
