"""Regression: centreline_id must survive the graph JSON round-trip.

The Centreline loader sets centreline_id on every edge (the key that links TMC
counts + road restrictions to the graph), but export_graph_json silently dropped
it — breaking the closure join. This locks the round-trip.
"""

from __future__ import annotations

import networkx as nx

from torontosim.graph import schema
from torontosim.graph.routing import export_graph_json, import_graph_json


def test_centreline_id_round_trips(tmp_path):
    g = nx.MultiDiGraph()
    g.add_node(0, x=-79.40, y=43.64)
    g.add_node(1, x=-79.39, y=43.65)
    g.add_edge(
        0,
        1,
        key=0,
        **schema.make_edge(
            edge_id="e0",
            from_node=0,
            to_node=1,
            road_class="primary",
            length_m=100.0,
            speed_kmh=50.0,
            lanes=2.0,
            capacity=1000.0,
            base_time_min=0.1,
            one_way=True,
            geometry=[[43.64, -79.40], [43.65, -79.39]],
            centreline_id=2920777,
        ),
    )
    p = tmp_path / "g.json"
    export_graph_json(g, str(p))
    g2 = import_graph_json(str(p), heal=False)

    cids = [d.get("centreline_id") for _, _, d in g2.edges(data=True)]
    assert cids == [2920777]
