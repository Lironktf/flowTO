"""
End-to-end proof that the road graph + mutations + routing work together.

Scenario:
  1. Load the prebuilt Toronto graph (JSON; falls back to GraphML).
  2. Pick two Toronto locations (Liberty Village -> Downtown Core).
  3. Snap each to its nearest node.
  4. Find the shortest path (by current_time_min).
  5. Close one edge that lies on that path.
  6. Recalculate the shortest path.
  7. Report whether the route changed, with before/after distance + time.

Run directly:
    python -m tests.test_graph_mutation

Or under pytest:
    pytest tests/test_graph_mutation.py -s
"""

from __future__ import annotations

import os
import sys

# Make the package importable when run as a plain script (pytest uses conftest).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import networkx as nx  # noqa: E402

from torontosim.graph.mutations import close_edge  # noqa: E402
from torontosim.graph.routing import (  # noqa: E402
    build_edge_index,
    find_shortest_path,
    get_nearest_node,
    import_graph_json,
    summarize_graph,
)

# Two well-known Toronto spots.
LIBERTY_VILLAGE = (43.6370, -79.4200)
DOWNTOWN_CORE = (43.6510, -79.3810)

JSON_PATH = os.path.join(_REPO_ROOT, "data", "graph", "toronto_drive_graph.json")
GRAPHML_PATH = os.path.join(_REPO_ROOT, "data", "graph", "toronto_drive_graph.graphml")


def load_graph() -> nx.MultiDiGraph:
    """Load the prebuilt graph, preferring JSON and falling back to GraphML."""
    if os.path.exists(JSON_PATH):
        graph = import_graph_json(JSON_PATH)
    elif os.path.exists(GRAPHML_PATH):
        graph = nx.read_graphml(GRAPHML_PATH, force_multigraph=True)
        build_edge_index(graph)
    else:
        raise FileNotFoundError(
            "No prebuilt graph found. Run `python -m src.graph.build_graph` first."
        )
    return graph


def _fmt(result: dict) -> str:
    if not result["found"]:
        return "no route found"
    return (
        f"{len(result['nodes'])} nodes / {len(result['edges'])} edges, "
        f"{result['total_distance_m'] / 1000:.2f} km, "
        f"{result['total_time_min']:.2f} min"
    )


def test_graph_mutation():
    """The actual test (pytest-discoverable, also callable from main)."""
    graph = load_graph()
    summarize_graph(graph)

    assert graph.number_of_nodes() > 0, "graph has no nodes"
    assert graph.number_of_edges() > 0, "graph has no edges"

    origin = get_nearest_node(graph, *LIBERTY_VILLAGE)
    dest = get_nearest_node(graph, *DOWNTOWN_CORE)
    print(f"\nOrigin node (Liberty Village): {origin}")
    print(f"Destination node (Downtown Core): {dest}")
    assert origin != dest, "origin and destination snapped to the same node"

    # ---- before -------------------------------------------------------
    before = find_shortest_path(graph, origin, dest, weight="current_time_min")
    print(f"\nBEFORE closure: {_fmt(before)}")
    assert before["found"], "no route found before closure"
    assert len(before["edges"]) > 0, "route has no edges"

    # ---- close one edge on the path -----------------------------------
    edge_to_close = before["edges"][len(before["edges"]) // 2]
    print(f"Closing edge on path: {edge_to_close}")
    close_edge(graph, edge_to_close)

    # ---- after --------------------------------------------------------
    after = find_shortest_path(graph, origin, dest, weight="current_time_min")
    print(f"AFTER closure:  {_fmt(after)}")
    assert after["found"], "no route found after closure (graph too sparse?)"

    # The closed edge must not appear in the new route.
    assert edge_to_close not in after["edges"], "closed edge still used in route!"

    changed = before["nodes"] != after["nodes"]
    print(f"\nRoute changed: {changed}")
    print(
        "Distance delta: "
        f"{(after['total_distance_m'] - before['total_distance_m']) / 1000:+.2f} km"
    )
    print("Travel-time delta: " f"{after['total_time_min'] - before['total_time_min']:+.2f} min")

    # Closing an edge on the optimal path can only keep or worsen the route.
    assert after["total_time_min"] >= before["total_time_min"] - 1e-6
    print("\nPASS: graph, mutation, and routing all work.")


if __name__ == "__main__":
    test_graph_mutation()
