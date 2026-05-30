"""RAPIDS GPU smoke test — the gate for every GPU phase (P04/P05/P10).

Tries to import cuDF + cuGraph and run a single-source shortest-path on a tiny
graph on the GB10. Prints exactly one verdict token on the last line:

    RAPIDS_OK            -> cudf+cugraph import and SSSP ran on GPU. Enable backend=gpu.
    RAPIDS_FALLBACK_CPU  -> import or kernel failed (sm_121/GB10 unverified). Use backend=cpu.

Run on the Spark via the harness:
    scripts/spark/run.sh "python scripts/spark/smoke_rapids.py"

The verdict is recorded in infra/README-spark.md and consumed by the sim
engine's backend flag. A FALLBACK verdict is NOT a build failure — CPU is the
demo path; this just records reality.
"""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        import cudf  # noqa: F401
        import cugraph
        import cupy  # noqa: F401

        print("cudf:", cudf.__version__)
        print("cugraph:", cugraph.__version__)

        # Tiny directed graph: 0->1->2->3 plus a shortcut 0->3 (weight 10).
        src = [0, 1, 2, 0]
        dst = [1, 2, 3, 3]
        wgt = [1.0, 1.0, 1.0, 10.0]
        gdf = cudf.DataFrame({"src": src, "dst": dst, "weight": wgt})

        G = cugraph.Graph(directed=True)
        G.from_cudf_edgelist(gdf, source="src", destination="dst", edge_attr="weight")

        dist = cugraph.sssp(G, source=0)
        d = dist.set_index("vertex").to_pandas()["distance"].to_dict()
        # Shortest 0->3 is via 0->1->2->3 = 3.0, not the direct 10.0 edge.
        assert abs(d[3] - 3.0) < 1e-6, f"unexpected SSSP distance to 3: {d[3]}"
        print(f"SSSP 0->3 distance = {d[3]} (expected 3.0)")
        print("RAPIDS_OK")
        return 0
    except Exception as exc:  # noqa: BLE001 — any failure means fall back to CPU.
        print(f"RAPIDS smoke failed: {exc!r}", file=sys.stderr)
        traceback.print_exc()
        print("RAPIDS_FALLBACK_CPU")
        return 0  # exit 0: a fallback verdict is a valid, recorded outcome.


if __name__ == "__main__":
    raise SystemExit(main())
