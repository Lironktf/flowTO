# P13 Stage-2 — activation-gate result (real Toronto closures)

Run 2026-05-31 on the GB10, full **Centreline** graph (44,257 nodes / 93,720 edges).
Artifact: `data/gnn/stage2_metrics.json` (gitignored). Reproduce:

```
bash scripts/spark/run.sh "PYTHONPATH=.:src python scripts/feedback/finetune_stage2.py \
  --residual-solver blast --sim-backend gpu --gate-min-n 10"
```

## Verdict: **SHIP GNN** — it beats the sim on held-out real closures

| metric (held-out, flow units) | GNN | sim | 
|---|---:|---:|
| RMSE | **128.1** | 406.3 |
| MAE | **94.9** | 315.2 |
| rank top-k overlap | **0.80** | 0.40 |

`err_gnn < err_sim − ε` with `n = 38 ≥ min_n` → the gate ships the GNN. The Stage-2
fine-tune lowered held-out residual RMSE ~3× vs the sim's own residual and doubled the
worst-edge rank overlap.

## Data realized (honest counts)
- 2,696 CART restrictions → **111 distinct real closures** with an in-window TMC count
  (313 restriction×site rows); all 111 geocoded to a closed graph edge.
- **310 / 313** observation sites mapped to a graph edge (3 exact centreline matches +
  307 nearest-edge — TMC counts are intersection-keyed; see spec 13 §A). 0 unmapped.
- Temporal held-out split (latest closures): **89 train / 22 test** closures →
  **38 held-out observed edges** scored by the gate.
- **Openings: not modeled** (real opening yield ≈ 0; Stage-1 sim-pretrain carries the
  opening physics). Reported, not padded.

## Method + caveats (do not overstate)
- **Solver = blast** (all-or-nothing over the affected subgraph), used for *both* the
  Stage-1 pretrain pairs and the Stage-2 residuals, so the warm-start is method-consistent.
  This drops the full BPR equilibrium feedback — fast (whole run **337 s** vs ~40 min on
  the full solver) but lower fidelity. The "sim" the GNN beats here is therefore the
  blast-AON sim. **A full-equilibrium parity run (`--residual-solver full`) should confirm
  the verdict holds** (spec 15 T-perf.3) before treating "beats the sim" as final.
- The sim's residual RMSE is large (~406) because the grounded OD only reconciles ~128 TMC
  sensors, so `sim_open` is a rough baseline; part of the GNN's win is learning to correct a
  systematically-off baseline. Still a real, verifiable improvement — but calibration-grade,
  not a precision claim.
- n = 38 held-out edges across 22 closures clears the min-n guard but is thin; the verdict
  is "ship on current evidence," to be re-confirmed as the closure set grows.

## Bottom line
The feedback loop closes end-to-end on real Toronto data: sim-pretrained residual GNN →
fine-tuned on real closure residuals → **gated, and it beats the sim** on held-out real
closures. Next: the full-solver parity run, then wire the model as the P10 pre-screen.
