# Spark test harness (`gx10-4f5f`)

The DGX Spark (GB10, Grace-Blackwell, CUDA 13.0) is our GPU/LLM validation box.
We build and unit-test on the CPU dev box; GPU/LLM paths are **validated here
over SSH** and gated by smoke tests. **GPU is never a build blocker** — a
failed/deferred smoke verdict means the CPU path is the demo path.

## Coordinates (from `docs/01-spark-inventory.md`, probed 2026-05-29)
- Host: `asus@gx10-4f5f` · Tailscale `100.124.76.16` · WiFi `10.10.53.33`
- Auth: SSH **key** (no password) from the dev box.
- GPU: NVIDIA **GB10**, Driver 580.142, **CUDA 13.0** (`/usr/local/cuda-13.0`).
- Ollama installed and ready (user in `ollama` group).
- Use an **isolated** remote venv `~/flowto-venv` (do not collide with `~/venv`).

## One-time remote setup
```bash
ssh asus@gx10-4f5f
python3 -m venv ~/flowto-venv && source ~/flowto-venv/bin/activate
pip install -e ~/torontosim                # after first push
# GPU extra (aarch64 + CUDA 13 wheels):
pip install cudf-cu13 cugraph-cu13 --extra-index-url=https://pypi.nvidia.com
# Copilot model (check `ollama list` first):
ollama pull nemotron3:33b
```

## Harness (in `scripts/spark/`)
| Script | Purpose |
|---|---|
| `env.sh` | Connection vars (`SPARK_HOST`, `REMOTE_DIR=~/torontosim`, `REMOTE_VENV`). Override via env. |
| `push.sh` | `rsync` working tree → Spark (excludes `data/`, `.git`, venvs, `__pycache__`). |
| `run.sh "<cmd>"` | Run `<cmd>` on the Spark inside `REMOTE_DIR` + activated venv. |
| `pull.sh <remote> <local>` | `rsync` an artifact back. |
| `smoke_rapids.py` | Gate for GPU phases → prints `RAPIDS_OK` or `RAPIDS_FALLBACK_CPU`. |
| `smoke_ollama.py` | Gate for the copilot → prints `OLLAMA_OK` / `OLLAMA_NO_MODEL` / `OLLAMA_DOWN`. |

Round-trip:
```bash
scripts/spark/push.sh
scripts/spark/run.sh "python -c 'import sys; print(sys.platform, sys.version)'"
scripts/spark/run.sh "python scripts/spark/smoke_rapids.py"
scripts/spark/run.sh "python scripts/spark/smoke_ollama.py"
```

## Gating verdicts (recorded — consumed by P04/P05/P09/P10)
| Gate | Verdict | When | Notes |
|---|---|---|---|
| Spark reachable (Tailscale/SSH) | ✅ **REACHABLE** | 2026-05-30 | Key auth OK via both `gx10-4f5f` and `100.124.76.16`. |
| RAPIDS (`smoke_rapids.py`) | ✅ **RAPIDS_OK** | 2026-05-30 | cuDF/cuGraph **26.04.000** import + SSSP verified on GB10. `backend=gpu` is available (still smoke-gated per phase). Installed via `pip install cudf-cu13 cugraph-cu13 --extra-index-url=https://pypi.nvidia.com` into `~/flowto-venv`. |
| Ollama (`smoke_ollama.py`) | ✅ **OLLAMA_OK** | 2026-05-30 | `nemotron3:33b` returned parseable scenario JSON in ~1.07s (think=False+format=json). Models also present: `nemotron-3-super`, `qwen3:30b`, `qwen3.6:35b`, `gemma4:26b`. |
| cuOpt (`smoke_cuopt.py`) | ⏭️ **CUOPT_UNAVAILABLE** | 2026-05-30 | No `cuopt` module / service on the Spark. **Deferred** — the P10 heuristic optimizer (sim-as-verifier) always returns an improving plan; cuOpt is a validated add-on, not on the critical path. |

> **Build policy unchanged:** CPU remains the default demo path. GPU/LLM stays
> behind flags (`backend=gpu`, live copilot) and is validated per phase via the
> harness; the green verdicts above mean those upgrades are *available*, not
> mandatory. Re-run the smokes after any remote venv change.
