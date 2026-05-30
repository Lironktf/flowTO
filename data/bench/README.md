# `data/bench/` — performance results (gitignored outputs)

`python -m torontosim.perf.bench` writes `results.json` + `results.md` here:
the **full-city vs blast-radius recompute** latency comparison (the headline
perf table) on the loaded graph. Outputs are gitignored; the committed
`README.md` documents the schema.

Schema (`results.json`):
- `closed_edge`, `n_edges`
- `recompute_full_ms`, `recompute_blast_ms`, `speedup`
- `affected_subgraph_fraction`, `affected_edges`
- `full_summary`, `blast_summary`

On the Spark, `scripts/spark/nsight_sim.sh` / `nsight_llm.sh` add Nsight Systems
timelines (cuDF / cuGraph / Ollama) — the on-device GPU evidence.
