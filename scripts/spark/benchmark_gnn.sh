#!/usr/bin/env bash
# Run the GNN same-task feature A/B benchmark on the DGX Spark (GB10).
# Trains main's GraphSAGE on each feature config (baseline / pruned / ablations)
# over the SAME frozen dataset+split+seed — only the columns vary — so any delta
# is the model's, not env/data skew. See docs/specs/13-feedback-loop.md §G.
#
#   scripts/spark/benchmark_gnn.sh [EPOCHS]   # default 30
#
# Needs torch/PyG on the box (verified). Syncs the GNN code (push.sh excludes
# models/) + the label CSVs (push.sh excludes data/), runs on the GB10, pulls the
# report back to data/gnn/benchmark_report.{json,md}.
set -euo pipefail
source "$(dirname "$0")/env.sh"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EPOCHS="${1:-30}"

echo "[bench] sync GNN code + feedback module + label CSVs -> $SPARK_HOST"
rsync -az --exclude '__pycache__' --exclude '*.pt' -e "ssh $SSH_OPTS" \
  "$REPO_ROOT/models/gnn/" "$SPARK_HOST:$REMOTE_DIR/models/gnn/"
rsync -az --exclude '__pycache__' -e "ssh $SSH_OPTS" \
  "$REPO_ROOT/src/torontosim/feedback/" "$SPARK_HOST:$REMOTE_DIR/src/torontosim/feedback/"
rsync -az -e "ssh $SSH_OPTS" \
  "$REPO_ROOT/data/model/training_dataset.csv" \
  "$REPO_ROOT/data/model/validation_dataset.csv" \
  "$SPARK_HOST:$REMOTE_DIR/data/model/"

echo "[bench] run GraphSAGE A/B ($EPOCHS epochs) on the GB10"
ssh $SSH_OPTS "$SPARK_HOST" \
  "cd $REMOTE_DIR && { [ -f $REMOTE_VENV/bin/activate ] && source $REMOTE_VENV/bin/activate || true; } && \
   PYTHONPATH=src python -m torontosim.feedback.benchmark.run --backend graphsage --epochs $EPOCHS"

echo "[bench] pull report -> data/gnn/"
mkdir -p "$REPO_ROOT/data/gnn"
for f in benchmark_report.md benchmark_report.json; do
  rsync -az -e "ssh $SSH_OPTS" "$SPARK_HOST:$REMOTE_DIR/data/gnn/$f" "$REPO_ROOT/data/gnn/$f" || true
done
echo "[bench] done — see data/gnn/benchmark_report.md"
