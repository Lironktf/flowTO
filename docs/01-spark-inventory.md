# 01 — Spark Inventory (gx10-4f5f)

Probed 2026-05-29. Host: `asus@gx10-4f5f` — Tailscale `100.124.76.16`, WiFi `10.10.53.33`.
SSH works with **key auth** (no password) from the UBentu dev box.

## Hardware
- **GPU:** NVIDIA **GB10** (Grace-Blackwell), Driver 580.142, **CUDA 13.0**. Idle at probe time.
- **Unified memory:** 121 GiB total, ~114 GiB free. (CPU+GPU share it — big models OK.)
- **CPU:** 20 ARM (aarch64) cores.
- **Disk:** 916 GB, ~620 GB free.
- OS: NVIDIA DGX Spark v7.5.0, kernel 6.17 nvidia, aarch64.

## Software present
- **Ollama** installed (`/usr/local/bin/ollama`) and user is in the **`ollama` group** → local LLM serving ready. ✅
- **CUDA toolkit** at `/usr/local/cuda-13.0` (nvcc NOT on PATH — add `export PATH=/usr/local/cuda-13.0/bin:$PATH`).
- Python **3.12.3** (system); `pip`/`pip3` present; **no `uv`**.
- Node **v24.15.0** (for the deck.gl frontend). ✅
- **Docker 29.2.1** installed, but `asus` is **not in `docker` group** → needs `sudo docker ...` (user HAS sudo).
- git 2.43.
- Existing LLM workspace in `~`: `llama.cpp/`, `unsloth/`, `venv/`, `run_qwen3.6.sh`, `run_gemma4.sh`, `run_openclaw.sh`.
  → torch/vllm/warp likely live in `~/venv`, not system python. **Make our own venv to avoid collisions.**

## Setup gaps / TODO before building
- [ ] `python3 -m venv ~/flowto-venv` (isolate from existing `~/venv`)
- [ ] Add CUDA to PATH for nvcc (only if we compile CUDA/Warp kernels)
- [ ] `pip install` core stack (see `02-architecture.md`)
- [ ] `ollama pull` a Nemotron model (check `ollama list` for what's cached first)
- [ ] Decide docker vs. bare-metal for services (bare-metal simpler given the `sudo` friction)
- [ ] Confirm GB10 visible to torch in our venv (`torch.cuda.is_available()`)

## Access notes
- This is shared hardware (`asus` account, existing LLM work present). **Don't delete others' dirs.**
- Reachable over Tailscale, so the team can SSH in remotely + the web UI can be tunnelled.
