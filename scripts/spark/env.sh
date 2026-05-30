#!/usr/bin/env bash
# Shared connection settings for the DGX Spark (GB10) test harness.
# Source this from the other scripts: `source "$(dirname "$0")/env.sh"`.
#
# Coordinates from docs/01-spark-inventory.md (probed 2026-05-29):
#   host gx10-4f5f, Tailscale 100.124.76.16, key auth, CUDA 13.0, Ollama ready.

# Prefer the Tailscale hostname; override via env if your ssh config differs.
export SPARK_HOST="${SPARK_HOST:-asus@gx10-4f5f}"
# Fallback IP if DNS/MagicDNS isn't resolving the hostname.
export SPARK_IP="${SPARK_IP:-100.124.76.16}"
# Where our code lives on the Spark, and the isolated remote venv.
export REMOTE_DIR="${REMOTE_DIR:-~/torontosim}"
export REMOTE_VENV="${REMOTE_VENV:-~/flowto-venv}"

# ssh/rsync options: batch mode (never prompt), short connect timeout so an
# unreachable Spark fails fast instead of blocking the build.
export SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new}"
