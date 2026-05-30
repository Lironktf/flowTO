# P00 — Repo restructure, environment & Spark test harness

| | |
|---|---|
| **Priority** | Core (everything depends on it) |
| **Depends on** | — |
| **Owner hint** | Glue/PM owner |
| **Status** | not started |

## Goal
Merge Liron's `liron/model` prototype into a clean, installable monorepo (`torontosim` package + `frontend/`),
stand up the dev environment, CI, and the **SSH-to-Spark test harness** so every later phase has a one-command
way to (a) run CPU tests locally and (b) validate GPU/LLM paths on `gx10-4f5f`. **No behavior changes** to
Liron's pipeline — pure restructure + scaffolding, with import shims so nothing breaks.

**Why / rubric tie-in:** Completeness + Spark story. A reproducible local pipeline that the demo starts from raw
data is explicitly what judges reward; the Spark harness is how we turn "it's fast on GB10" into evidence.

## Current state
- `liron/model` has `src/{graph,model,simulation}`, `tests/`, `data/`, `models/demand_model.pkl`, `scripts/`,
  `requirements.txt`, two READMEs. Imports are flat (`from src.graph import ...` / relative). macOS `.DS_Store`
  and malformed `data/raw/weather/weather_2023 6_00.csv` artifacts present.
- `bentobranch` has the planning docs + `explainer.html` + smoke scripts, but **none of Liron's code yet**.

## Target state
- One branch (`bentobranch` → eventually `main`) containing both the planning docs **and** Liron's code, restructured to the layout in `ROADMAP.md §4`.
- `pip install -e .` works; `pytest` green; `ruff`/`black` configured; pre-commit hides `.DS_Store`.
- `scripts/spark/` harness: push code to the Spark, run a remote command, pull artifacts back.
- CI (GitHub Actions) runs CPU tests on every push.

### In scope
Restructure, packaging, tooling, CI, Spark harness, data hygiene, import shims, env files.
### Out of scope
Any change to simulation/demand/graph logic (those are P02–P05). Frontend app scaffold beyond an empty `frontend/` placeholder (real scaffold is P07).

## Design / implementation plan
1. **Merge Liron's code onto `bentobranch`.** `git merge origin/liron/model` (or cherry-pick the code, keeping
   planning docs). Resolve `README.md`/`.gitignore` conflicts; keep both doc sets.
2. **Move to a package.** `src/{graph,model,simulation}` → `src/torontosim/{graph,model,simulation}`. Add
   `src/torontosim/__init__.py` exposing version. Add **import shims**: a top-level `src/graph/__init__.py` that
   re-exports from `torontosim.graph` so Liron's tests + `train_*.sh` keep working during migration; remove shims
   in a later cleanup task once call-sites are updated.
3. **`pyproject.toml`** — `setuptools`/`hatchling`; `project.dependencies` from `requirements.txt`
   (networkx, osmnx, scikit-learn, xgboost, pandas, numpy, joblib, scipy); dev extras
   (`pytest`, `ruff`, `black`, `pre-commit`). Define optional extras: `[gpu]` (cudf-cu13, cugraph-cu13),
   `[sim]` (aequilibrae), `[ai]` (ollama, sentence-transformers, chromadb), `[api]` (fastapi, uvicorn, websockets).
   GPU/AI extras are **not** installed locally — only on the Spark.
4. **Data hygiene.** Add `.DS_Store`, `data/`, `models/*.pkl`, `*.graphml` (large) to `.gitignore`; keep a small
   committed `data/README.md` with provenance. Fix/normalize the malformed weather filenames in
   `datapipeline` (P01 owns the real fetch). Decide: large committed data (`toronto_drive_graph.graphml` 314k lines)
   → move to a `data/` artifact fetched by `datapipeline`, not committed.
5. **Spark SSH harness** (`scripts/spark/`):
   - `env.sh` — `SPARK_HOST=asus@gx10-4f5f` (Tailscale `100.124.76.16`), key auth, `REMOTE_DIR=~/torontosim`.
   - `push.sh` — `rsync -az --exclude data --exclude .git ./ $SPARK_HOST:$REMOTE_DIR`.
   - `run.sh "<cmd>"` — `ssh $SPARK_HOST "cd $REMOTE_DIR && source ~/flowto-venv/bin/activate && <cmd>"`.
   - `pull.sh <remote_path> <local>` — rsync artifacts back.
   - `smoke_rapids.py` / `smoke_ollama.py` — the gating GPU/LLM smoke tests (used by P04/P09).
6. **CI** — `.github/workflows/ci.yml`: matrix py3.12, `pip install -e .[dev,sim]`, `ruff check`, `pytest -q`.
   GPU/LLM tests are marked `@pytest.mark.spark` and **skipped in CI** (run only via the Spark harness).
7. **Makefile / task runner** — `make install`, `make test`, `make lint`, `make spark-test`.

## Data / models / sources
- Spark coordinates from `docs/01-spark-inventory.md` (host, Tailscale, `~/flowto-venv`, CUDA 13, Ollama).
- RAPIDS aarch64 install line (for the Spark extra), per `research/04`: `pip install cudf-cu13 cugraph-cu13 --extra-index-url=https://pypi.nvidia.com`.

## Files to create / modify (delegation list)
**Create**
- `pyproject.toml`, `Makefile`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`
- `src/torontosim/__init__.py`
- `src/graph/__init__.py`, `src/model/__init__.py`, `src/simulation/__init__.py` (shims → re-export)
- `scripts/spark/{env.sh,push.sh,run.sh,pull.sh,smoke_rapids.py,smoke_ollama.py}`
- `data/README.md`, `infra/README-spark.md`
**Move**
- `src/graph/* → src/torontosim/graph/*`, `src/model/* → src/torontosim/model/*`, `src/simulation/* → src/torontosim/simulation/*`
- `tests/* ` stay at `tests/` (update imports to `torontosim.*`)
**Modify**
- `.gitignore` (DS_Store, data, large artifacts), `README.md` (merge), `requirements.txt` → folded into `pyproject.toml`

## Test-driven design
- **Smoke import test** (`tests/test_packaging.py`, write first): `import torontosim; from torontosim.graph import routing; from torontosim.simulation import simulate_traffic` — fails until the move is done.
- **Liron's tests still pass** after the move (regression gate): `tests/test_graph_mutation.py`, `tests/test_simulation.py` — update imports, must stay green.
- **Shim test:** `from src.graph import routing` still resolves (until shims removed).
- **CI gate:** `ruff check` clean; `pytest -q` green on py3.12.

## Verification
**Local (CPU):**
```
make install && make lint && make test     # all green
python -c "import torontosim; print(torontosim.__version__)"
```
**On Spark (over SSH):** establish the harness works end-to-end:
```
scripts/spark/push.sh
scripts/spark/run.sh "python -c 'import sys; print(sys.platform, sys.version)'"
scripts/spark/run.sh "python scripts/spark/smoke_rapids.py"   # PASS/FAIL gate for all GPU phases
```
`smoke_rapids.py` prints `RAPIDS_OK` if `cudf`+`cugraph` import and an SSSP runs on GB10; else `RAPIDS_FALLBACK_CPU` — recorded in `infra/README-spark.md` and consumed by P04/P05/P10.

## Tasks (subtickets)
- [ ] T00.1 Merge `liron/model` into `bentobranch`, resolve conflicts, keep both doc sets — *0.5d*
- [ ] T00.2 Move `src/*` → `src/torontosim/*`, add shims, fix imports in tests — *0.5d*
- [ ] T00.3 `pyproject.toml` + extras + `Makefile` + lint/format config — *0.5d*
- [ ] T00.4 Data hygiene: `.gitignore`, de-commit large artifacts, fix weather filenames, `data/README.md` — *0.5d*
- [ ] T00.5 Spark SSH harness scripts + `smoke_rapids.py` + `smoke_ollama.py` — *0.5d*
- [ ] T00.6 GitHub Actions CI (CPU tests, lint), `@pytest.mark.spark` skip — *0.5d*
- [ ] T00.7 Verify: local green + Spark harness round-trip + RAPIDS smoke verdict recorded — *0.5d*

## Risks / fallbacks
- **Large committed graph/data bloats the merge** → de-commit and refetch via `datapipeline` (P01); if time-pressed, keep `toronto_drive_graph.json` (small) committed, drop the 314k-line `.graphml`.
- **Spark unreachable over Tailscale at build time** → harness degrades to "scripts present, smoke deferred"; CPU path unaffected.
- **Shim confusion** → track shim-removal as an explicit cleanup task once all call-sites use `torontosim.*`.
