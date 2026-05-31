"""P08 — transit trajectories: monotonic secs, on-shape position, no wrap."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api_scenarios import _small_state
from torontosim.api import create_app
from torontosim.transit.routes import demo_routes, demo_trajectories, route_geometries
from torontosim.transit.trajectories import (
    build_trajectory,
    interpolate_position,
    parse_gtfs_time,
)

TRIP = [
    {"stop_sequence": 0, "arrival_time": "14:00:00", "lng": -79.41, "lat": 43.635},
    {"stop_sequence": 1, "arrival_time": "14:05:00", "lng": -79.40, "lat": 43.636},
    {"stop_sequence": 2, "arrival_time": "14:10:00", "lng": -79.39, "lat": 43.637},
]


def test_parse_gtfs_time_no_wrap_past_midnight():
    assert parse_gtfs_time("14:05:00") == 14 * 3600 + 300
    # After-midnight service (>24h) must not wrap.
    assert parse_gtfs_time("25:30:00") == 25 * 3600 + 1800


def test_trajectory_has_monotonic_seconds():
    traj = build_trajectory(TRIP)
    assert traj["timestamps"] == [50400, 50700, 51000]
    assert all(b >= a for a, b in zip(traj["timestamps"], traj["timestamps"][1:]))
    assert len(traj["path"]) == 3


def test_midtrip_position_lies_between_bracketing_stops():
    traj = build_trajectory(TRIP)
    # Halfway between stop 0 (14:00) and stop 1 (14:05) → 14:02:30.
    pos = interpolate_position(traj, 50400 + 150)
    assert pos is not None
    # x between -79.41 and -79.40, y between 43.635 and 43.636.
    assert -79.41 <= pos[0] <= -79.40
    assert 43.635 <= pos[1] <= 43.636


def test_inactive_trip_returns_none():
    traj = build_trajectory(TRIP)
    assert interpolate_position(traj, 0) is None  # before first stop
    assert interpolate_position(traj, 99999) is None  # after last stop


def test_route_geometries_tag_mode():
    routes = route_geometries(
        [{"route_id": "509", "route_type": 0, "path": [[-79.41, 43.63], [-79.40, 43.64]]}]
    )
    assert routes[0]["mode"] == "streetcar"


def test_demo_set_nonempty():
    assert len(demo_routes()) == 2
    trajs = demo_trajectories()
    assert len(trajs) > 0
    assert all(len(t["path"]) >= 2 for t in trajs)


def test_transit_api_endpoints():
    client = TestClient(create_app(_small_state()))
    r = client.get("/transit/routes?agencies=ttc")
    assert r.status_code == 200
    assert len(r.json()["routes"]) > 0  # real TTC routes now (was a 2-route demo)
    t = client.get("/transit/trajectories?agencies=ttc")
    assert t.status_code == 200
    assert len(t.json()["trajectories"]) > 0
