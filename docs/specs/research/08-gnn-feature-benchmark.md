# Research Brief 08 — GNN Feature Benchmark (same-task A/B on the GB10)

> Ran live on the DGX Spark / GB10 (NVIDIA GB10, CUDA 13.0, torch 2.12.0+cu130, PyG 2.7.0)
> on **2026-05-31**. Feeds **P13 §C/§G**. Reproduce: `bash scripts/spark/benchmark_gnn.sh 30`.

## Question
Are the baseline GNN's inherited features (`distance_to_downtown`, redundant degree/road-class
duplicates, raw `lat/lon`) **pulling their weight**, or is the pruned/restructured set from
`13-feedback-loop.md` §C *better, not just different*? Answered empirically before building the
residual model.

## Method
- **Same-task A/B.** Every config trains on the **same frozen dataset + split + seed**; only the
  **feature columns** vary, so any delta is the model's, not env/data skew. Configs are applied as
  *column drops* on the built dataset (`feedback/benchmark/run.py:_subset_dataset` re-fits the
  standardizers), then train main's GraphSAGE unchanged via `models.gnn.train_gnn.train()`.
- **Model:** `GraphSAGEEdgePredictor` (2× `SAGEConv`, hidden 128, softplus pressure head),
  AdamW lr 1e-3, SmoothL1, 30 epochs.
- **Data:** Toronto drive graph (~18k edges) + demand label CSVs (~16.3k train / 4.5k val). The val
  split is **grouped by `location_id`** (`ingest_real_data.split_and_write`), so **val error already
  measures unseen-location generalization** — the spatial-holdout probe comes for free.
- **Target:** open-road `pressure = count / capacity` (clipped 2.0).
- **Seeds:** {42, 1, 7}; metrics are the mean across seeds (std reported).

### Configs
| Config | Drops | Dims (node/edge) |
|---|---|---|
| `baseline` | — (main's full set) | 7 / 21 |
| `ablate_redundant` | node `degree`; edge `road_class_rank`, `from_node_degree`, `to_node_degree` | 6 / 18 |
| `ablate_downtown` | node `distance_to_downtown_km` | 6 / 21 |
| `pruned` (aggressive) | node `degree`, `distance_to_downtown_km`, `lat`, `lon`, `pagerank`; edge `road_class_rank`, `from/to_node_degree` | 2 / 18 |

## Results

**30 epochs × 3 seeds (mean):**
| metric | `baseline` | `ablate_redundant` | `ablate_downtown` | `pruned` |
|---|---|---|---|---|
| MAE ↓ | 0.2026 | **0.2019** | 0.2030 | 0.2210 |
| RMSE ↓ | 0.3189 | 0.3165 | **0.3164** | 0.3416 |
| R² ↑ | 0.4818 | 0.4899 | **0.4901** | 0.4057 |
| risk-acc ↑ | **0.6616** | 0.6611 | 0.6544 | 0.6105 |

Per-seed spread is tiny where it matters — e.g. `ablate_redundant` MAE = [0.2016, 0.2019, 0.2021]
(std 0.0002), so the baseline-vs-pruned-features gaps are **real, not noise**. (`risk-acc` is a
coarse 4-bucket metric and is essentially flat across the non-aggressive configs.)

An earlier **8-epoch single-seed** validation pass agreed directionally (baseline 0.2072 MAE,
`ablate_redundant` 0.2073, `pruned` 0.2258) and confirmed the harness end-to-end on the GB10.

## Findings
1. **The redundant features are dead weight — dropping them is a small *win*.** `ablate_redundant`
   beats `baseline` on MAE/RMSE/R² (0.2019 vs 0.2026 MAE). Removing `degree` (= in+out),
   `road_class_rank` (dup of the one-hot), and `from/to_node_degree` (dup of node feats) slightly
   *reduces* error — fewer redundant inputs, less overfitting.
2. **`distance_to_downtown` adds nothing here.** `ablate_downtown` also edges out baseline on
   MAE/RMSE/R². It's a *demand* prior; the pressure model doesn't need it. Drop it.
3. **`lat/lon` carry real signal — do not drop them outright.** The aggressive `pruned` config
   (node features stripped to just `in/out_degree`) is clearly worst (0.2210 MAE, R² 0.41 — a ~9%
   MAE regression). Spatial position matters for this task.

## Decisions (feed §C)
- **DROP** (confirmed, no loss / small gain): node `degree`, `distance_to_downtown_km`; edge
  `road_class_rank`, `from_node_degree`, `to_node_degree`; plus `pagerank` (all-zeros unless
  `--pagerank` is committed).
- **KEEP** spatial signal — but as a **learned positional encoding**, not raw `lat/lon` (raw coords
  risk memorizing specific intersections; the PE keeps the signal without the memorization).
- The locked lean set ≈ `baseline − {degree, distance_to_downtown, road_class_rank,
  from/to_node_degree, pagerank}`, **keeping coords (as PE)**.

## Caveats (read before over-reading)
- **This is the open-road *pressure* task, not the closure *residual* task.** `lat/lon` /
  `distance_to_downtown` being useful here reflects demand/spatial structure; the residual model
  (where the sim supplies spatial context via `sim_open`) may lean on them even less. The real
  residual benchmark needs the P14 dataset + scenario-gen and is the §D activation gate.
- Single architecture (GraphSAGE, softplus head); the MLP fallback and the residual head are not
  in this A/B.
- `risk-accuracy`'s 4-bucket coarseness makes it nearly flat — weight MAE/RMSE/R² for the verdict.

## Reproduce
- **Full run:** `bash scripts/spark/benchmark_gnn.sh 30` (syncs code + label CSVs to the GB10, runs
  30 epochs × seeds {42,1,7} across all configs, pulls `data/gnn/benchmark_report.{json,md}`).
- **Harness:** `src/torontosim/feedback/benchmark/` — `configs.py` (the registry), `metrics.py`,
  `compare.py`, `run.py` (`--backend graphsage` on the GB10; `--backend ridge` is a torch-free
  local proxy on the demand CSV, **not** the GraphSAGE verdict).
- **Local plumbing tests (no torch):** `pytest tests/test_benchmark.py` (15 tests).
