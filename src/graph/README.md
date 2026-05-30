# Toronto Road Graph Layer

The road-network layer for the flowTO traffic simulator. It downloads a
drivable road graph for Toronto from OpenStreetMap (via OSMnx), enriches every
edge with the fields the simulation engine needs, and provides mutation +
routing utilities for running "what-if" scenarios (road closures, construction,
new roads) and comparing congestion before vs. after.

This layer is **car-only** and intentionally hackathon-practical: reasonable
defaults over perfect road accuracy.

## Layout

```
src/graph/
  config.py        # defaults (speed/lanes/capacity), geo + time helpers
  build_graph.py   # download from OSM + enrich + save  (needs osmnx)
  mutations.py     # close/reopen/change_capacity/add/remove/close_node
  routing.py       # nearest node/edge, shortest path, JSON I/O, summary
data/graph/
  toronto_drive_graph.graphml   # NetworkX-reloadable
  toronto_drive_graph.json      # clean simulation JSON (below)
tests/
  test_graph_mutation.py        # end-to-end proof
```

Only `build_graph.py` needs **OSMnx**. `mutations.py` and `routing.py` depend
only on **networkx** (+ stdlib), so the simulation engine can consume the graph
without OSMnx installed.

## Rebuild the graph

```bash
pip install osmnx networkx          # build needs osmnx; consumers need only networkx

# Default: fast point-radius download of downtown Toronto (~7 km radius),
# which covers Liberty Village and the Downtown Core (used by the test).
python -m src.graph.build_graph

# Whole city (slow, large):
python -m src.graph.build_graph --full

# Named place:
python -m src.graph.build_graph --place "Toronto, Ontario, Canada"

# Custom point + radius (metres):
python -m src.graph.build_graph --center 43.65 -79.39 --radius 8000
```

This writes both `data/graph/toronto_drive_graph.graphml` and
`data/graph/toronto_drive_graph.json`.

## Run the proof

```bash
python -m tests.test_graph_mutation      # or: pytest tests/test_graph_mutation.py -s
```

It loads the graph, snaps Liberty Village + Downtown Core to nodes, routes
between them, closes an edge on the path, reroutes, and prints whether the
route changed plus the before/after distance and travel time.

## Graph model

A `networkx.MultiDiGraph` (directed; parallel edges allowed). Nodes are
intersections/endpoints; edges are directed road segments. OSMnx stores
longitude as `x` and latitude as `y`; we mirror those into `lon`/`lat`.

OSM almost never names intersections, so each node's `name` is synthesised from
the streets that meet there: 2+ distinct street names become
`"King Street West & Spadina Avenue"`, a single street stays as that street
name (a midblock point), and a node where every incident road is unnamed keeps
`name = null`. Any genuine OSM node name is preserved.

Edges are addressed by a stable string `edge_id` (`"{u}-{v}-{key}"`). An
`edge_id -> (u, v, key)` index is cached on the graph and rebuilt on load via
`build_edge_index(graph)`.

### JSON format

```json
{
  "nodes": [
    { "id": "...", "lat": 43.6, "lon": -79.4,
      "name": "King Street West & Spadina Avenue", "degree": 4 }
  ],
  "edges": [
    {
      "id": "...", "from": "...", "to": "...",
      "road_name": "King St W", "road_class": "secondary",
      "length_m": 132.4, "one_way": true,
      "speed_kmh": 50, "lanes": 2, "capacity": 1800,
      "base_time_min": 0.159, "current_time_min": 0.159,
      "status": "open", "load": 0, "pressure": 0,
      "geometry": [[43.64, -79.41], [43.64, -79.40]]
    }
  ]
}
```

`current_time_min` may be the string `"Infinity"` for closed edges (JSON has no
native infinity); `import_graph_json` converts it back to `float('inf')`.

## Edge field reference

| Field              | Meaning |
|--------------------|---------|
| `edge_id`          | Stable id `"{from}-{to}-{key}"`. |
| `from` / `to`      | Endpoint node ids (directed: traffic flows from → to). |
| `road_name`        | OSM street name, if any. |
| `road_class`       | Normalised OSM `highway` class (motorway/trunk/primary/secondary/tertiary/residential/…); `*_link` collapsed to its parent. |
| `length_m`         | Segment length in metres (OSM `length`, else straight-line). |
| `one_way`          | `true`/`false`/`null` from OSM `oneway`. |
| `speed_kmh`        | Free-flow speed (OSM `maxspeed`, else estimated by class). |
| `lanes`            | Lane count (OSM `lanes`, else estimated by class). |
| `capacity`         | Est. throughput `lanes × veh/hour/lane` (see defaults). |
| `base_time_min`    | Free-flow time `length_km / speed_kmh × 60`. |
| `current_time_min` | Live travel time used for routing; starts at `base_time_min`, set to ∞ when closed. The simulation engine updates this as congestion builds. |
| `status`           | `"open"` or `"closed"`. |
| `load`             | Vehicles currently assigned (engine-owned; starts 0). |
| `pressure`         | Congestion metric, e.g. load/capacity (engine-owned; starts 0). |
| `geometry`         | `[[lat, lon], …]` polyline for map rendering, or `null`. |

### Estimation defaults (when OSM is missing data)

`capacity = lanes × vehicles_per_hour_per_lane`

| road_class            | veh/hr/lane | speed km/h | lanes |
|-----------------------|-------------|------------|-------|
| motorway              | 1800        | 100        | 3     |
| trunk / primary       | 1200        | 80 / 60    | 3 / 2 |
| secondary             | 900         | 50         | 2     |
| tertiary              | 700         | 40         | 1     |
| residential / local   | 400         | 30         | 1     |
| (fallback `default`)  | 600         | 40         | 1     |

## API quick reference

```python
from src.graph.routing import (
    import_graph_json, export_graph_json, summarize_graph,
    get_nearest_node, get_nearest_edge, find_shortest_path, build_edge_index,
)
from src.graph.mutations import (
    close_edge, reopen_edge, change_capacity, add_edge, remove_edge, close_node,
)

g = import_graph_json("data/graph/toronto_drive_graph.json")

o = get_nearest_node(g, 43.6370, -79.4200)
d = get_nearest_node(g, 43.6510, -79.3810)
route = find_shortest_path(g, o, d, weight="current_time_min")
# route -> {found, nodes, edges, total_cost, total_distance_m, total_time_min}

close_edge(g, route["edges"][0])      # status->closed, capacity->0, time->inf
reopen_edge(g, route["edges"][0])     # restores prior capacity + time
change_capacity(g, some_edge_id, 0.5) # construction: halve capacity
new_id = add_edge(g, o, d, "New Rd", speed_kmh=50, lanes=2, capacity=1800)
remove_edge(g, new_id)                # delete entirely
close_node(g, o)                      # close every edge touching a node
```

### Mutation semantics

- **`close_edge`** — reversible: stashes pre-close capacity/time, then sets
  `status="closed"`, `capacity=0`, `current_time_min=∞`. Routing skips it.
- **`reopen_edge`** — restores the stashed capacity/time (or `base_time_min`).
- **`change_capacity`** — multiplies current `capacity`; leaves status/time alone.
- **`add_edge`** — new segment between two existing nodes; length from node
  coords (haversine), time derived from length + speed; returns the new id.
- **`remove_edge`** — deletes the edge (use `close_edge` for reversible).
- **`close_node`** — closes every incoming and outgoing edge of a node; returns
  the list of closed edge ids.

`find_shortest_path` excludes closed edges (and any with non-finite weight), so
a closed road is routed around rather than producing an infinite-cost path.

## Notes / deviations

- The spec lists `get_nearest_node(lat, lon)` / `get_nearest_edge(lat, lon)`;
  these take the graph as the first argument here (`get_nearest_node(graph, lat,
  lon)`) so they work standalone without a global graph singleton.
- Nearest-node/edge use a haversine / equirectangular approximation (no extra
  deps), which is accurate at city scale.
