# Research Brief 05 — Local AI stack (Nemotron / cuOpt / RAG) on the Spark

> Feeds **P09 (copilot), P10 (optimizer)**. All on-device, no cloud. Defaults: **Ollama** for LLM, **cuOpt container** for optimization. NIM/TRT-LLM are stretch.

## Nemotron on Ollama (exact tags)
121 GiB UMA fits any of these; the newer `nemotron-3-*` are MoE (low active params → fast).
| `ollama pull` tag | Params | Disk | Ctx | Tools | Notes |
|---|---|---|---|---|---|
| `nemotron-mini:4b` | 4B dense | 2.7 GB | 4K | ✅ | RAG QA + function calling; tiny context. Good pure tool-router/fallback. |
| `nemotron-3-nano:4b` | 4B dense | 2.8 GB | 256K | ✅ (`tools`,`thinking`) | Great latency + long ctx. |
| **`nemotron-3-nano:30b`** | 30B / **3.5B active** MoE | 24 GB (q4) | up to 1M | ✅ | Mamba-2+MoE; fast + smart. **Recommended copilot brain.** |
| `nemotron-3-super` | 120B / 12B active MoE | (fits quantized) | long | ✅ agentic | Max quality, slower first-token. Verify tag/size on model page. |
| `nemotron:70b` | 70B dense (Llama-3.1-Nemotron) | 43 GB (q4) | 128K | ✅ | Dense → slower than MoE nanos. |

```bash
ollama pull nemotron-3-nano:30b      # copilot default
ollama pull nemotron-mini:4b         # fast fallback / pure tool-router
```
**Flags:** confirm `nemotron-3-super` exact quant tag/size on its page; pin a known-good Ollama version (an aarch64 Spark hang was reported on one build) and smoke-test `ollama run` early. Nemotron reasoning models: use `think:False` + `format:json` or the response comes back empty.

## Structured tool calling (recommended + snippet)
Two layers: (1) **Ollama native structured outputs** (`format=<JSON Schema>`) constrains decoding to schema-valid JSON; (2) **Pydantic validate + re-ask loop** for rules the schema can't express (e.g. `edge_ids` must exist). Generate the JSON Schema *from* Pydantic so they never drift. Beats outlines/instructor for a hackathon (no extra inference stack).
```python
from typing import Literal
from enum import Enum
from pydantic import BaseModel, Field, ValidationError
from ollama import Client
ollama = Client(); MODEL = "nemotron-3-nano:30b"
class InterventionType(str, Enum):
    capacity_reduction="capacity_reduction"; closure="closure"; signal_retiming="signal_retiming"
class PreviewIntervention(BaseModel):
    action: Literal["preview_intervention"]; intervention_type: InterventionType
    edge_ids: list[int] = Field(min_length=1); duration_min: int = Field(ge=0, le=1440)
def plan(nl: str, valid_edges: set[int]) -> PreviewIntervention:
    schema = PreviewIntervention.model_json_schema()
    for _ in range(3):
        r = ollama.chat(model=MODEL, format=schema, options={"temperature":0},
            messages=[{"role":"system","content":"Translate to one tool call. Only use edge_ids in the network."},
                      {"role":"user","content":nl}])
        try: call = PreviewIntervention.model_validate_json(r["message"]["content"])
        except ValidationError as e: nl = f"{nl}\nInvalid: {e}. Fix it."; continue
        bad = set(call.edge_ids) - valid_edges
        if bad: nl = f"{nl}\nedge_ids {sorted(bad)} don't exist."; continue
        return call
    raise ValueError("no valid tool call")
```
Reuse the pattern for "explain results" (free-text, no `format=`) with RAG context in the system prompt.

## NIM / TRT-LLM verdict — **stretch, not the demo path. Default to Ollama.**
NIM on Spark exists (official `NVIDIA/dgx-spark-playbooks`; containers use a `-dgx-spark` suffix, ARM64+Blackwell-specific). Friction: needs **NGC API key + nvcr.io login** (cloud auth at setup — pre-stage before offline), Docker+sudo+NVIDIA Container Toolkit on aarch64, 10–50 GB pulls, **thin model coverage** (only a few have `-dgx-spark` builds). TensorRT-LLM runs but means engine builds — too much yak-shaving. **Ollama is the power-on-to-inference path.**

## cuOpt (availability + fit) — **usable locally**
NVIDIA GPU decision-optimization (VRP/TSP/PDP, LP, MILP, QP), **open source Apache-2.0**, current 26.08.
- pip (cu12): `pip install --extra-index-url=https://pypi.nvidia.com cuopt-server-cu12==26.06.* cuopt-sh-client==26.06.*`; conda via rapidsai; **Docker** `nvidia/cuopt:latest-cuda12.9-py3.13` (safer on CUDA-13 Spark). **Linux aarch64 supported.**
- API: `POST /cuopt/request` → `GET /cuopt/solution/{id}`; sections `cost_matrix_data`, `task_data`, `fleet_data`, `solver_config`.
- **Fit:** OD-bundle reassignment (VRP+capacity) ✅; work-window scheduling (VRP-TW + MILP) ✅; constrained detours (partial). **Caveat:** city traffic isn't a pure VRP (congestion/induced-demand coupling) — use cuOpt for *constrained sub-problems*, pair with the assignment layer; don't claim it "solves traffic."

## Local RAG — embedded, in-process
**Recommended:** `sentence-transformers` (`all-MiniLM-L6-v2`, CPU, ~80 MB) + **Chroma** (persistent) or **FAISS** (flat). Chunk bylaws, embed at startup, top-k=4 → copilot system prompt. Or Ollama embeddings (`nomic-embed-text`) to keep stack to "Ollama + FAISS." NeMo Retriever = NIM friction → skip.

### Demo-safe defaults
Copilot LLM `nemotron-3-nano:30b` (fallback `nemotron-mini:4b`); tool calls Ollama `format=`+Pydantic+re-ask; optimizer cuOpt Docker; RAG MiniLM+Chroma. Avoid on critical path: NIM, TRT-LLM, NeMo Retriever. **Pre-stage before offline:** model pulls, cuOpt image, embed model, (if NIM) NGC key + containers.

### Links
nemotron-3-nano: https://ollama.com/library/nemotron-3-nano · nemotron-mini: https://ollama.com/library/nemotron-mini · Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs · cuOpt: https://github.com/NVIDIA/cuopt · cuOpt quick-start: https://docs.nvidia.com/cuopt/user-guide/latest/cuopt-server/quick-start.html · DGX Spark playbooks: https://deepwiki.com/NVIDIA/dgx-spark-playbooks · Ollama Spark perf: https://ollama.com/blog/nvidia-spark-performance
