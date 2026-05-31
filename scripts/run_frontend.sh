#!/usr/bin/env bash
# Stable launcher for the Vite dev server (fixed port, logged), so it survives
# detached and is easy to restart. Proxies /api -> localhost:8000 (see vite.config).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
exec npx vite --port 5175 --strictPort
