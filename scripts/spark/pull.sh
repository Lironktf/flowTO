#!/usr/bin/env bash
# Pull an artifact back from the Spark.
#   scripts/spark/pull.sh <remote_path_relative_to_REMOTE_DIR> <local_dest>
set -euo pipefail
source "$(dirname "$0")/env.sh"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <remote_path> <local_dest>" >&2
  exit 2
fi
REMOTE_PATH="$1"
LOCAL_DEST="$2"

mkdir -p "$(dirname "$LOCAL_DEST")"
echo "[spark] rsync $SPARK_HOST:$REMOTE_DIR/$REMOTE_PATH -> $LOCAL_DEST"
rsync -az -e "ssh $SSH_OPTS" "$SPARK_HOST:$REMOTE_DIR/$REMOTE_PATH" "$LOCAL_DEST"
echo "[spark] pull OK"
