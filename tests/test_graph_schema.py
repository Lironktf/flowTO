"""P02 canonical-schema tests + OSMnx/Centreline parity.

* validate_graph rejects an edge missing capacity/confidence;
* a centreline fixture graph and the committed OSMnx graph both pass
  validate_graph and expose identical canonical edge field names.
"""

from __future__ import annotations

import os

import networkx as nx
import pytest

from torontosim.graph import schema
from torontosim.graph.centreline_loader import build_centreline_graph
from torontosim.graph.routing import import_graph_json

# --- tiny centreline fixture: a 2-block one-way + two-way grid ------------- #
INTERSECTIONS = [
    {"INTERSECTION_ID": 1, "geometry": {"type": "Point", "coordinates": [-79.400, 43.640]}},
    {"INTERSECTION_ID": 2, "geometry": {"type": "Point", "coordinates": [-79.395, 43.640]}},
    {"INTERSECTION_ID": 3, "geometry": {"type": "Point", "coordinates": [-79.395, 43.645]}},
    # duplicate (multi-level) row for node 3 — must dedupe.
    {"INTERSECTION_ID": 3, "geometry": {"type": "Point", "coordinates": [-79.395, 43.645]}},
]
TCL = [
    {
        "CENTRELINE_ID": 1001,
        "LINEAR_NAME_FULL": "King St W",
        "FROM_INTERSECTION_ID": 1,
        "TO_INTERSECTION_ID": 2,
        "ONEWAY_DIR_CODE": 0,  # two-way -> two edges
        "FEATURE_CODE_DESC": "Major Arterial",
    },
    {
        "CENTRELINE_ID": 1002,
        "LINEAR_NAME_FULL": "Bay St",
        "FROM_INTERSECTION_ID": 2,
        "TO_INTERSECTION_ID": 3,
        "ONEWAY_DIR_CODE": 1,  # one-way from->to -> single edge 2->3
        "FEATURE_CODE_DESC": "Minor Arterial",
    },
    {  # a river — must be filtered out (not a road class)
        "CENTRELINE_ID": 9999,
        "FROM_INTERSECTION_ID": 1,
        "TO_INTERSECTION_ID": 3,
        "ONEWAY_DIR_CODE": 0,
        "FEATURE_CODE_DESC": "River",
    },
]


def test_validate_rejects_missing_capacity_and_confidence():
    g = nx.MultiDiGraph()
    g.add_node(1, x=-79.4, y=43.64)
    g.add_node(2, x=-79.39, y=43.64)
    # An edge missing capacity + confidence.
    g.add_edge(
        1,
        2,
        key=0,
        edge_id="e",
        from_node=1,
        to_node=2,
        road_class="primary",
        length_m=100.0,
        one_way=True,
        speed_kmh=50.0,
        lanes=2.0,
        base_time_min=0.1,
        current_time_min=0.1,
        status="open",
        load=0,
        pressure=0,
        geometry=None,
        road_name="X",
    )
    with pytest.raises(schema.SchemaError):
        schema.validate_graph(g)


def test_centreline_fixture_builds_and_validates():
    g = build_centreline_graph(TCL, INTERSECTIONS)
    schema.validate_graph(g)

    # River filtered out; node 3 deduped.
    assert g.number_of_nodes() == 3
    # King two-way -> 2 edges; Bay one-way -> 1 edge; river dropped -> 3 total.
    assert g.number_of_edges() == 3

    # Directionality: two-way King exists both ways; one-way Bay only 2->3.
    assert g.has_edge(1, 2) and g.has_edge(2, 1)
    assert g.has_edge(2, 3) and not g.has_edge(3, 2)

    # Every edge carries a confidence dict + centreline_id link.
    for _u, _v, d in g.edges(data=True):
        assert isinstance(d["confidence"], dict) and d["confidence"]
        assert d["centreline_id"] in (1001, 1002)


def test_parity_osmnx_and_centreline_same_fields():
    """Both sources expose identical canonical edge field names + validate."""
    cl = build_centreline_graph(TCL, INTERSECTIONS)
    schema.validate_graph(cl)

    json_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "graph", "toronto_drive_graph.json"
    )
    osm = import_graph_json(json_path)
    schema.ensure_confidence(osm)  # committed graph predates confidence
    schema.validate_graph(osm)

    cl_fields = set(next(iter(cl.edges(data=True)))[2])
    osm_fields = set(next(iter(osm.edges(data=True)))[2])
    for f in schema.CANONICAL_EDGE_FIELDS:
        assert f in cl_fields, f"centreline edge missing {f}"
        assert f in osm_fields, f"osmnx edge missing {f}"
