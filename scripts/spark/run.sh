#!/usr/bin/env bash
# Run a command on the Spark inside the project dir + remote venv.
#   scripts/spark/run.sh "python scripts/spark/smoke_rapids.py"
set -euo pipefail
source "$(dirname "$0")/env.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 \"<remote command>\"" >&2
  exit 2
fi
REMOTE_CMD="$*"

# Activate the venv if present; otherwise fall back to system python so a
# missing venv produces a clear error rather than a silent wrong interpreter.
ssh $SSH_OPTS "$SPARK_HOST" \
  "cd $REMOTE_DIR && { [ -f $REMOTE_VENV/bin/activate ] && source $REMOTE_VENV/bin/activate || true; } && $REMOTE_CMD"
