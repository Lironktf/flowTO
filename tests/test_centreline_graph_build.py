"""W2 — build the real Centreline graph from the baked parquet store.

Bakes the committed CKAN fixtures (W1) to parquet, then loads them through the
production wrapper (``centreline_loader.load_from_parquet``), proving the
geometry survives as WKT, the graph validates against the canonical schema, and
it routes a sample path. The OSMnx baseline path stays the default.
"""

from __future__ import annotations

import os

from torontosim.datapipeline import bake
from torontosim.graph import schema
from torontosim.graph.centreline_loader import load_from_parquet
from torontosim.graph.routing import find_shortest_path

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "raw")


def _bake_store(tmp_path):
    pq_dir = tmp_path / "parquet"
    pq_dir.mkdir()
    bake.bake_centreline(os.path.join(FIX, "centreline.csv"), pq_dir / "centreline.parquet")
    bake.bake_intersections(
        os.path.join(FIX, "intersections.geojson"), pq_dir / "intersections.parquet"
    )
    bake.bake_bridges(os.path.join(FIX, "bridges.geojson"), pq_dir / "bridges.parquet")
    return pq_dir


def test_centreline_graph_builds_validates_and_routes(tmp_path):
    pq_dir = _bake_store(tmp_path)
    graph = load_from_parquet(str(pq_dir))

    # Nodes come from the intersection file (which only carries geometry, no
    # lat/lon columns) — proving the loader reads the baked ``geometry_wkt``.
    assert graph.number_of_nodes() >= 3
    assert graph.number_of_edges() >= 1

    # Canonical schema clean (same contract as the OSMnx baseline).
    schema.validate_graph(graph)

    # The river segment (FEATURE_CODE_DESC=River) is filtered out — drive only.
    cids = {d.get("centreline_id") for _u, _v, d in graph.edges(data=True)}
    assert 99999999 not in cids
    assert 13466414 in cids  # Yonge St (major arterial) kept

    # Real polyline geometry survived the WKT round-trip (3-pt Yonge segment).
    yonge = [d for _u, _v, d in graph.edges(data=True) if d.get("centreline_id") == 13466414]
    assert any(len(d["geometry"]) >= 3 for d in yonge)

    # Routes a sample path 100 -> 300 across the baked grid.
    path = find_shortest_path(graph, 100, 300)
    assert path["found"]
    assert path["nodes"][0] == 100 and path["nodes"][-1] == 300


def test_bridge_vert_clear_attaches_to_centreline_edge(tmp_path):
    pq_dir = _bake_store(tmp_path)
    graph = load_from_parquet(str(pq_dir))
    # Bridge BR-1 is on CENTRELINE_ID 13466500 with VERT_CLEAR 4.3.
    matched = [
        d
        for _u, _v, d in graph.edges(data=True)
        if d.get("centreline_id") == 13466500 and d.get("vert_clear_m") == 4.3
    ]
    assert matched


def test_graph_source_resolver_defaults_to_osmnx(tmp_path):
    """The api graph-source switch defaults to OSMnx (baseline-safe)."""
    from torontosim.api._bootstrap import resolve_graph_source

    assert resolve_graph_source(None, env={}) == "osmnx"
    assert resolve_graph_source(None, env={"TS_GRAPH_SOURCE": "centreline"}) == "centreline"
    assert resolve_graph_source("centreline", env={}) == "centreline"
