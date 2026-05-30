"""Heal inconsistent one-way tagging on two-way arterials.

OpenStreetMap sometimes tags individual segments of a fundamentally two-way
road as ``oneway=yes`` (digitization quirks, turn-lane splits, edits). That
orphans downstream nodes: closing the single feeding segment disconnects them,
so trips to those nodes are silently dropped — which makes road closures look
artificially beneficial.

Repair principle: **a named road that is two-way on *any* segment should be
two-way on *all* of its segments.** For each one-way segment of such a road that
is missing its reverse direction, add the mirrored edge. Streets that are
one-way along their *entire* length (e.g. downtown Richmond/Adelaide) have no
two-way segment, so they are never touched.
"""

from __future__ import annotations

import networkx as nx

from .routing import build_edge_index, make_edge_id


def heal_oneway_arterials(graph: nx.MultiDiGraph, mode: str = "all") -> int:
    """Add missing reverse edges so one-way segments become two-way. Returns count.

    ``mode``:
      * ``"all"`` (default) — make **every** one-way edge two-way. Demo-grade:
        OSM one-way tags in this dataset are unreliable and the artifacts they
        cause (closing a one-way segment orphans a node → trips silently
        stranded) hurt the demo more than the lost one-way realism. Assumes the
        roads are two-way, which is true for the vast majority here. For
        authoritative directionality, rebuild from Centreline (`centreline_loader`).
      * ``"named"`` — conservative: only heal one-way segments of a road that is
        two-way on some *named* segment elsewhere (leaves genuine one-way streets
        like downtown Richmond/Adelaide alone).

    Mutates ``graph`` in place and rebuilds the edge index. Added reverse edges
    copy the forward segment's attributes (capacity, speed, length, …), reverse
    the geometry, set ``one_way=False``, and carry ``_healed_reverse``.
    """
    twoway_names = None
    if mode == "named":
        twoway_names = {
            d["road_name"]
            for _, _, d in graph.edges(data=True)
            if d.get("road_name") and d.get("one_way") is False
        }

    added = 0
    for u, v, _k, d in list(graph.edges(keys=True, data=True)):
        if d.get("one_way") is not True:
            continue
        if u == v:
            continue
        if twoway_names is not None and d.get("road_name") not in twoway_names:
            continue  # conservative mode: genuinely one-way road, leave it
        if graph.has_edge(v, u):
            continue  # reverse already present (real or previously healed)

        rd = dict(d)
        rd["one_way"] = False
        rd["status"] = rd.get("status", "open")
        geom = rd.get("geometry")
        if isinstance(geom, list):
            rd["geometry"] = list(reversed(geom))
        rd["edge_id"] = make_edge_id(v, u, 0)
        rd["_healed_reverse"] = True
        graph.add_edge(v, u, key=0, **rd)
        # Mark the forward segment as two-way too, for consistency.
        d["one_way"] = False
        added += 1

    build_edge_index(graph)
    return added
