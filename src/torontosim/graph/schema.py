"""Canonical road-graph schema shared by both loaders (P02).

Liron's OSMnx builder and the new Centreline loader must emit the **same**
enriched edge/node schema so routing, mutations, and the simulation engine are
source-agnostic. This module is the single source of truth for that schema and
for the per-field **confidence** label, plus a ``validate_graph`` used by tests.
"""

from __future__ import annotations

import networkx as nx

# Confidence of an inferred field's value.
CONFIDENCE_LABELS = ("observed", "inferred", "default", "manual")

# Every edge must carry these. Some may be ``None`` (nullable below), but the
# key must exist so consumers never KeyError.
CANONICAL_EDGE_FIELDS = (
    "edge_id",
    "from_node",
    "to_node",
    "road_name",
    "road_class",
    "length_m",
    "one_way",
    "speed_kmh",
    "lanes",
    "capacity",
    "base_time_min",
    "current_time_min",
    "status",
    "load",
    "pressure",
    "geometry",
    "confidence",
)

# Fields allowed to be ``None`` (e.g. unnamed roads, missing geometry).
NULLABLE_EDGE_FIELDS = frozenset({"road_name", "geometry", "one_way", "confidence"})

# Inferred fields we attach a confidence label to.
CONFIDENCE_FIELDS = ("lanes", "speed_kmh", "capacity", "one_way")

# Nodes must locate themselves (x=lon, y=lat).
CANONICAL_NODE_FIELDS = ("x", "y")


class SchemaError(ValueError):
    """Raised when a graph violates the canonical schema."""


def default_confidence(label: str = "default") -> dict[str, str]:
    """A confidence dict (one label per inferred field)."""
    if label not in CONFIDENCE_LABELS:
        raise ValueError(f"invalid confidence label: {label!r}")
    return {f: label for f in CONFIDENCE_FIELDS}


def ensure_confidence(graph: nx.MultiDiGraph, *, label: str = "default") -> nx.MultiDiGraph:
    """Make a legacy graph schema-conformant in place.

    Backfills the ``confidence`` dict and the denormalized ``from_node`` /
    ``to_node`` keys (redundant with the edge endpoints, but part of the
    canonical schema) on graphs built before they existed — e.g. Liron's
    committed JSON.
    """
    for u, v, data in graph.edges(data=True):
        conf = data.get("confidence")
        if not isinstance(conf, dict) or not conf:
            data["confidence"] = default_confidence(label)
        data.setdefault("from_node", u)
        data.setdefault("to_node", v)
    return graph


def validate_graph(graph: nx.MultiDiGraph, *, require_nodes: bool = True) -> None:
    """Assert the graph conforms to the canonical schema. Raise ``SchemaError``.

    Checks: every edge has all canonical fields (non-nullable ones non-None),
    a valid ``confidence`` dict, and every node has x/y.
    """
    if graph.number_of_edges() == 0:
        raise SchemaError("graph has no edges")

    for u, v, data in graph.edges(data=True):
        missing = [f for f in CANONICAL_EDGE_FIELDS if f not in data]
        if missing:
            raise SchemaError(f"edge {u}->{v} missing fields: {missing}")
        for f in CANONICAL_EDGE_FIELDS:
            if f not in NULLABLE_EDGE_FIELDS and data.get(f) is None:
                raise SchemaError(f"edge {u}->{v} field {f!r} is None (not nullable)")
        conf = data.get("confidence")
        if not isinstance(conf, dict):
            raise SchemaError(f"edge {u}->{v} confidence must be a dict, got {type(conf)}")
        bad = {k: lbl for k, lbl in conf.items() if lbl not in CONFIDENCE_LABELS}
        if bad:
            raise SchemaError(f"edge {u}->{v} invalid confidence labels: {bad}")
        cap = data.get("capacity")
        if not isinstance(cap, (int, float)) or cap <= 0:
            raise SchemaError(f"edge {u}->{v} capacity must be > 0, got {cap!r}")

    if require_nodes:
        for n, data in graph.nodes(data=True):
            for f in CANONICAL_NODE_FIELDS:
                if data.get(f) is None:
                    raise SchemaError(f"node {n} missing coordinate field {f!r}")


def make_edge(
    *,
    edge_id: str,
    from_node,
    to_node,
    road_class: str,
    length_m: float,
    speed_kmh: float,
    lanes: float,
    capacity: float,
    base_time_min: float,
    road_name=None,
    one_way=None,
    geometry=None,
    confidence: dict[str, str] | None = None,
    **extra,
) -> dict:
    """Build a canonical edge-attribute dict (status open, zero load/pressure)."""
    edge = {
        "edge_id": edge_id,
        "from_node": from_node,
        "to_node": to_node,
        "road_name": road_name,
        "road_class": road_class,
        "length_m": round(float(length_m), 3),
        "one_way": one_way,
        "speed_kmh": round(float(speed_kmh), 1),
        "lanes": float(lanes),
        "capacity": round(float(capacity), 1),
        "base_time_min": round(float(base_time_min), 4),
        "current_time_min": round(float(base_time_min), 4),
        "status": "open",
        "load": 0,
        "pressure": 0,
        "geometry": geometry,
        "confidence": confidence or default_confidence(),
    }
    edge.update(extra)
    return edge
