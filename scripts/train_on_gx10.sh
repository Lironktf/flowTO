#!/usr/bin/env bash
#
# Train the flowTO demand model on a remote NVIDIA box (e.g. ASUS Ascent GX10),
# then pull the trained model back to this machine.
#
# The GX10 is a GB10 Grace-Blackwell (aarch64 + CUDA) box. The current demand
# model is small tabular gradient boosting that trains in seconds on CPU, so the
# GX10 is overkill *for this model* — but this script makes remote/GPU training
# a one-liner for when the dataset or model grows (real counts, deep/temporal
# models, big hyper-parameter sweeps, or many parallel simulations).
#
# Usage:
#   scripts/train_on_gx10.sh user@gx10-host [backend]
#     backend: xgboost (GPU, default here) | sklearn | xgboost-cpu
#
# Prereqs on the GX10 (one-time): python3 + venv, and for GPU:
#   python3 -m venv ~/flowto-venv
#   ~/flowto-venv/bin/pip install -r requirements.txt
#   ~/flowto-venv/bin/pip install xgboost      # CUDA build for aarch64
#
set -euo pipefail

HOST="${1:?usage: train_on_gx10.sh user@host [backend]}"
BACKEND="${2:-xgboost}"
REMOTE_DIR="${REMOTE_DIR:-~/flowTO}"
REMOTE_VENV="${REMOTE_VENV:-~/flowto-venv}"

echo "==> Syncing project to ${HOST}:${REMOTE_DIR}"
# Push code + the training data + the graph; skip local venvs and big artifacts.
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude 'data/simulation' \
  ./ "${HOST}:${REMOTE_DIR}/"

echo "==> Training on ${HOST} (backend=${BACKEND})"
ssh "${HOST}" "cd ${REMOTE_DIR} && \
  FLOWTO_MODEL_BACKEND=${BACKEND} ${REMOTE_VENV}/bin/python -m \
  src.model.train_demand_model --train --backend ${BACKEND}"

echo "==> Pulling trained model back"
mkdir -p models
rsync -az "${HOST}:${REMOTE_DIR}/models/demand_model.pkl" models/demand_model.pkl

echo "==> Done. models/demand_model.pkl updated from ${HOST}."
echo "    (Inference runs locally; only training used the GX10.)"
