#!/usr/bin/env python3
"""Bake the committed Toronto graph into a static /edges fixture for the FAKE
frontend-only demo (no backend). Output mirrors the real `GET /api/edges`
payload shape (`{count, edges:[EdgeMeta]}`), so the mock fetch shim can serve it
verbatim. Geometry is the REAL graph geometry ([[lat, lng], ...]); everything
else in the demo (pressures, copilot, scenarios) is synthesised client-side.

On-disk graph uses keys: id / from / to / road_name / road_class / geometry.
The frontend EdgeMeta uses `edge_id` (== graph `id`); from/to are reconstructed
in the browser from the geometry endpoints (frontend api/graph.ts buildGraph),
so we only need idx / edge_id / geometry / road_name / road_class here.

Run from anywhere:
    python3 /home/anonabento/flowTO-fakedemo/scripts/gen_mock_edges.py
"""
from __future__ import annotations

import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "data", "graph", "toronto_drive_graph.json")
OUT = os.path.join(REPO, "frontend", "public", "mock", "edges.json")


def main() -> None:
    with open(SRC) as f:
        g = json.load(f)

    edges_out = []
    idx = 0
    for e in g["edges"]:
        geom = e.get("geometry")
        if not geom or len(geom) < 2:
            continue
        rg = [[round(float(la), 6), round(float(ln), 6)] for la, ln in geom]
        edges_out.append(
            {
                "idx": idx,
                "edge_id": e["id"],
                "geometry": rg,
                "road_name": e.get("road_name"),
                "road_class": e.get("road_class"),
            }
        )
        idx += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"count": len(edges_out), "edges": edges_out}, f, separators=(",", ":"))

    print(f"wrote {len(edges_out)} edges -> {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
