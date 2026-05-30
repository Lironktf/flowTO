#!/usr/bin/env bash
# Push the working tree to the Spark (code only — never data/, .git, venvs).
set -euo pipefail
source "$(dirname "$0")/env.sh"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "[spark] rsync $REPO_ROOT -> $SPARK_HOST:$REMOTE_DIR"
rsync -az --delete \
  --exclude '.git' \
  --exclude 'data' \
  --exclude 'models' \
  --exclude '.venv' \
  --exclude 'flowto-venv' \
  --exclude 'node_modules' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  -e "ssh $SSH_OPTS" \
  "$REPO_ROOT"/ "$SPARK_HOST:$REMOTE_DIR/"
echo "[spark] push OK"
