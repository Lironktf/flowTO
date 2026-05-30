#!/usr/bin/env bash
# Build the FULL citywide graph on the Spark (heavy) and pull it back as an
# OPT-IN, non-committed artifact. The committed downtown graph
# (data/graph/toronto_drive_graph.json) stays the test baseline + offline demo
# default; the full graph is loaded only via TS_GRAPH_JSON / TS_GRAPH_SOURCE.
#
#   scripts/spark/build_full_graph.sh            # full-city Centreline (real-data target)
#
# Requires the baked parquet store on the Spark first (centreline+intersections,
# +tmc for capacity calibration):
#   scripts/spark/fetch_and_bake.sh --only centreline,intersections,tmc
#
# NOTE: do NOT use `python -m torontosim.graph.build_graph --full` to make the
# full graph — that writes to the FIXED path data/graph/toronto_drive_graph.json
# and would CLOBBER the committed downtown baseline. This script uses
# `graph.build --source centreline --out <separate file>` so the baseline is
# never touched.
set -euo pipefail
HERE="$(dirname "$0")"
source "$HERE/env.sh"

OUT="data/graph/toronto_full_graph.json"

# 1) Push the current tree so the Spark builds with this exact code.
"$HERE/push.sh"

# 2) Build the citywide Centreline graph from the baked parquet, capacity-
#    calibrated against the real TMC parquet, to a SEPARATE output file.
"$HERE/run.sh" "pip install -e '.[data,api]' >/dev/null 2>&1 || true; \
  python -m torontosim.graph.build --source centreline --out $OUT"

# 3) Pull the full graph back (gitignored locally).
"$HERE/pull.sh" "$OUT" "./$OUT"

echo "[spark] full Centreline graph -> ./$OUT (gitignored; baseline untouched)."
echo "[spark] use it WITHOUT replacing the baseline, e.g.:"
echo "        TS_GRAPH_JSON=$OUT scripts/run_api.sh"
echo "        # or the live Centreline parquet path:"
echo "        TS_GRAPH_SOURCE=centreline scripts/run_api.sh"
