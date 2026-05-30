#!/usr/bin/env bash
#
# Run the demand-model training overnight on the ASUS GX10 (GB10, aarch64+CUDA).
#
# It syncs the project, builds the real train/val datasets from data/raw on the
# box, then launches a long GPU hyper-parameter sweep under `nohup` so it keeps
# running after you disconnect. In the morning, fetch the best model back.
#
# Usage:
#   scripts/train_overnight_gx10.sh launch       # sync + start the overnight sweep
#   scripts/train_overnight_gx10.sh status       # tail the remote log
#   scripts/train_overnight_gx10.sh fetch        # pull best model + logs back
#
# Config (env overrides):
#   HOST=asus@gx10-4f5f   TRIALS=200   REMOTE_DIR=~/flowTO   REMOTE_VENV=~/flowto-venv
#
set -euo pipefail

HOST="${HOST:-asus@gx10-4f5f}"
REMOTE_DIR="${REMOTE_DIR:-~/flowTO}"
REMOTE_VENV="${REMOTE_VENV:-~/flowto-venv}"
TRIALS="${TRIALS:-200}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTION="${1:-launch}"

case "$ACTION" in
launch)
  echo "==> Syncing project to ${HOST}:${REMOTE_DIR} (incl. data/raw)"
  rsync -az --delete \
    --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
    --exclude 'data/simulation' \
    ./ "${HOST}:${REMOTE_DIR}/"

  echo "==> One-time env check on ${HOST}"
  ssh "$HOST" "test -d ${REMOTE_VENV} || python3 -m venv ${REMOTE_VENV}; \
    ${REMOTE_VENV}/bin/pip install -q -r ${REMOTE_DIR}/requirements.txt xgboost"

  echo "==> Launching overnight ingest + sweep (${TRIALS} trials) under nohup"
  # Build real datasets first, then sweep on GPU; all logged, detached.
  ssh "$HOST" "cd ${REMOTE_DIR} && mkdir -p logs && \
    LOG=logs/overnight_\$(date +%Y%m%d_%H%M%S).log && \
    nohup bash -lc '
      ${REMOTE_VENV}/bin/python -m src.model.ingest_real_data && \
      FLOWTO_MODEL_BACKEND=xgboost ${REMOTE_VENV}/bin/python -m \
        src.model.train_demand_model --sweep --backend xgboost --trials ${TRIALS}
    ' > \$LOG 2>&1 & \
    echo \"started PID \$! -> ${REMOTE_DIR}/\$LOG\" && \
    ln -sf \$LOG logs/latest.log"
  echo "==> Launched. Monitor with: scripts/train_overnight_gx10.sh status"
  ;;

status)
  echo "==> Tailing ${HOST}:${REMOTE_DIR}/logs/latest.log (Ctrl-C to stop)"
  ssh "$HOST" "tail -n 40 -f ${REMOTE_DIR}/logs/latest.log"
  ;;

fetch)
  echo "==> Pulling best model + sweep log back from ${HOST}"
  mkdir -p models
  rsync -az "${HOST}:${REMOTE_DIR}/models/demand_model.pkl" models/demand_model.pkl
  rsync -az "${HOST}:${REMOTE_DIR}/models/sweep_results.json" models/sweep_results.json || true
  rsync -az "${HOST}:${REMOTE_DIR}/data/model/" data/model/ || true
  echo "==> Done. Best model is in models/demand_model.pkl"
  echo "    Validate locally: python -m tests.test_simulation"
  ;;

*)
  echo "usage: $0 {launch|status|fetch}" >&2; exit 1 ;;
esac
