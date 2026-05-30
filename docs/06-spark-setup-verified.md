# 06 — Spark Setup (VERIFIED)

Everything below was installed + tested on `gx10-4f5f` on 2026-05-29. All green.

## Project venv
`~/flowto-venv` (isolated from the existing `~/venv`). Python 3.12.3.

```bash
# reproduce:
python3 -m venv ~/flowto-venv
~/flowto-venv/bin/pip install -U pip
~/flowto-venv/bin/pip install -r ~/spark-hack-toronto/scripts/requirements.txt
```

## Verified components

| Component | Status | Notes |
|---|---|---|
| Core backend (fastapi, uvicorn, websockets, numpy, pandas, requests) | ✅ imports OK | |
| **GPU from Python** (NVIDIA Warp 1.13) | ✅ ran 5M-element CUDA kernel | sees GB10 `cuda:0`, sm_121, **122 GiB**, mempool enabled; Warp bundles CUDA 12.9, driver 13.0 |
| **Data stack** (osmnx 2.1, geopandas 1.1.3, shapely, networkx, gtfs_kit) | ✅ imports OK | ready to build the Toronto graph + parse GTFS |
| **Nemotron LLM** (Ollama, local) | ✅ structured JSON in ~1.8s | models cached: see below |

## Local models already cached in Ollama
- `nemotron-3-super:latest` (86 GB) — biggest, fits in unified memory
- `nemotron3:33b` (27 GB) — **default for the copilot** (fast, good)
- `gemma4:26b`, `qwen3.6:35b` — fallbacks

## ⭐ Canonical LLM recipe (reasoning model → structured output)
Nemotron is a **reasoning model**. To get reliable JSON out of the Ollama HTTP API:

```python
body = {
  "model": "nemotron3:33b",
  "system": SYSTEM, "prompt": PROMPT,
  "stream": False,
  "think": False,          # <-- REQUIRED
  "format": "json",        # <-- REQUIRED
  "options": {"temperature": 0.2},
  "keep_alive": "10m",     # keep model warm between calls (demo!)
}
# POST http://localhost:11434/api/generate
```

**Gotcha:** with thinking ON, `format:json` returns an **empty `response`** (output is diverted
to a separate `thinking` field). `think:False + format:json` fixes it. For complex optimizer
reasoning you can set `think:True` and extract the `{...}` block from `response` instead.
See `scripts/llm_debug.py` for the full A/B.

## Smoke tests (re-run anytime)
```bash
~/flowto-venv/bin/python ~/spark-hack-toronto/scripts/gpu_smoke.py      # GPU kernel
~/flowto-venv/bin/python ~/spark-hack-toronto/scripts/llm_smoke.py      # copilot JSON
~/flowto-venv/bin/python ~/spark-hack-toronto/scripts/llm_debug.py      # LLM strategy A/B
```

## Still TODO (next sessions)
- [ ] `nvcc` on PATH only if we hand-write CUDA (Warp doesn't need it): `export PATH=/usr/local/cuda-13.0/bin:$PATH`
- [ ] Frontend: `npm create` deck.gl + MapLibre app (Node v24 present)
- [ ] Data spike: build Toronto drive graph (osmnx) + parse TTC GTFS
- [ ] Keep Nemotron warm during demo (`keep_alive` or a warmup ping)
- [ ] Decide SUMO vs. Warp for the baseline sim (see `02-architecture.md`)

## Access reminders
- SSH key auth works: `ssh asus@gx10-4f5f`. Reachable over Tailscale (`100.124.76.16`).
- Shared box — existing `~/venv`, `~/llama.cpp`, `~/unsloth` belong to prior work. Don't touch.
- Docker needs `sudo` (user not in `docker` group). Prefer bare-metal venv for our services.
