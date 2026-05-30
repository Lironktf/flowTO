#!/usr/bin/env bash
# Launch the FlowTO frontend (Vite dev server) against a local P06 API.
#   scripts/run_frontend.sh            # http://localhost:5173
# Set VITE_API_BASE to point at a remote API (e.g. the Spark over Tailscale).
set -euo pipefail
cd "$(dirname "$0")/../frontend"

[ -d node_modules ] || npm install
exec npm run dev
