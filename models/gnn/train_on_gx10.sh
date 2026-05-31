#!/usr/bin/env bash
set -euo pipefail

EPOCHS="${1:-50}"
BATCH_SIZE="${2:-8192}"

if [ "${SKIP_INGEST:-0}" != "1" ]; then
  python -m src.torontosim.model.ingest_real_data
fi
python -m models.gnn.build_gnn_dataset --pagerank --label-strategy outgoing
python -m models.gnn.train_gnn \
  --dataset data/gnn/gnn_dataset.pt \
  --model-out models/gnn/gnn_edge_congestion.pt \
  --metrics-out data/gnn/training_metrics.json \
  --epochs "${EPOCHS}" \
  --batch-size "${BATCH_SIZE}" \
  --backend graphsage
python -m models.gnn.predict_gnn_baseline \
  --dataset data/gnn/gnn_dataset.pt \
  --model models/gnn/gnn_edge_congestion.pt \
  --output data/results/gnn_baseline_predictions.json \
  --hour 17 \
  --day-of-week 4 \
  --month 6 \
  --weather clear
