# Research Brief 04 — Sim engine (AequilibraE / BPR / FW) + RAPIDS-on-ARM

> Feeds **P04, P05**. Target: DGX Spark GB10, aarch64, CUDA 13, sm_121, 121 GiB. Dev box is x86 CPU-only.

## AequilibraE (oracle + optional backbone)
- **v1.6.2** (docs Apr 2026), pure-Python + Cython, **CPU-only, no CUDA**. `pip install aequilibrae` (aarch64 may need source build; no CUDA dep so runs on dev box + Spark CPU). https://github.com/AequilibraE/aequilibrae
- **Solvers:** MSA, `fw`, `cfw`, **`bfw` (bi-conjugate FW — recommended)**. VDFs: **BPR**, BPR2, Conical, INRETS, Akcelik.
```python
from aequilibrae import Project
from aequilibrae.paths import TrafficClass, TrafficAssignment
project = Project(); project.open("/path/to/proj")
project.network.build_graphs(fields=["free_flow_time","capacity"], modes=["c"])
g = project.network.graphs["c"]; g.set_graph("free_flow_time"); g.set_blocked_centroid_flows(True)
mat = project.matrices.get_matrix("demand"); mat.computational_view(["car"])
tc = TrafficClass("car", g, mat)
assig = TrafficAssignment(); assig.set_classes([tc])
assig.set_vdf("BPR"); assig.set_vdf_parameters({"alpha":0.15,"beta":4.0})
assig.set_capacity_field("capacity"); assig.set_time_field("free_flow_time")
assig.set_algorithm("bfw"); assig.max_iter=1000; assig.rgap_target=1e-6; assig.execute()
res = assig.results(); flows = res.matrix_ab     # directional equilibrium link flows
```
- **Skims:** `NetworkSkimming` / `g.compute_skims(cores=4)`. **OD/gravity/IPF built in** (`aequilibrae.distribution`: `SyntheticGravityModel`, `GravityApplication`, `Ipf`).
- **As oracle (idiomatic):** build a small TNTP network (SiouxFalls/Anaheim) + OD, run `bfw` to tight `rgap_target` (1e-8…1e-10), assert custom engine's `matrix_ab` within tolerance (relative L∞ ≤ 1e-2). Assert *within tolerance*, not bit-exact (different FW iterates reach the same UE). TNTP fixtures ship published equilibrium solutions.

## Assignment math (to implement on RAPIDS)
- **BPR:** `t = t0·(1 + α·(v/c)^β)`, standard **α=0.15, β=4** (US BPR 1964).
- **Frank-Wolfe UE:** (1) init `x=0`, `t=t0`; (2) BPR cost update → **all-or-nothing** onto shortest paths → aux flow `y`; (3) **line search** for `λ∈[0,1]` minimizing Beckmann objective (1-D bisection/golden); (4) `x ← x+λ(y−x)`; (5) **rgap** `=(Σt·x − Σt·y)/(Σt·x)`, stop ≤ target or max_iter. **CFW/BFW** = conjugate aux directions, same fixed point, fewer iters. **MSA** (`λ=1/k`) = simplest first-cut.
- **SUE/logit (stretch):** replace AON with logit loading — **Dial's STOCH** (implicit-path, link-based) inside MSA, or path-based logit. Ref: **Sheffi 1985, *Urban Transportation Networks*** (canonical for FW + Dial/SUE).

## RAPIDS-on-ARM feasibility — **RISK: MEDIUM. Must smoke-test on the Spark.**
**Known good:** `cudf-cu13` **26.4.0** ships an **aarch64 manylinux wheel** (py3.11–3.14); `cugraph-cu13` wheel via `pip install cudf-cu13 cugraph-cu13 --extra-index-url=https://pypi.nvidia.com`. CUDA-13 support matured RAPIDS 25.10→26.04. Driver ≥580.65 required (Spark on 580 — verify patch). Min CC 7.0 (GB10 = 12.1, above floor).
**Uncertainty (flag loudly):** **No source confirms RAPIDS running on sm_121.** RAPIDS docs never mention Blackwell/sm_120/sm_121/GB10; DGX-Spark community setup guides don't mention RAPIDS at all. **Saving grace:** sm_120 and sm_121 are **binary compatible** — if 26.04 wheels bake sm_120 cubins or forward-compat PTX, they should run on GB10; if only sm_90/sm_100, you hit "no kernel image." **Unverified — test it.** Broader ecosystem: sm_121 support is "incomplete"; cu12-only deps can break with `libcudart.so.12`.
**Smoke test (run first on the Spark; gate the GPU path):**
```bash
pip install cudf-cu13 cugraph-cu13 --extra-index-url=https://pypi.nvidia.com
python -c "import cudf,cugraph; e=cudf.DataFrame({'s':[0,1],'d':[1,2],'w':[1.,1.]}); \
  G=cugraph.Graph(directed=True); G.from_cudf_edgelist(e,source='s',destination='d',edge_attr='w'); \
  print(cugraph.sssp(G,0))"
```
"no kernel image" → wheels lack sm_120/PTX → fall back to CPU (try nightlies / source build `CUDAARCHS=121`). Prints flows → GPU live.

## cuGraph vs NetworkX API map
Build: `G=cugraph.Graph(directed=True); G.from_cudf_edgelist(e, source='src', destination='dst', edge_attr='weight', renumber=True)` (int32 verts).
| Op | cuGraph | NetworkX |
|---|---|---|
| Weighted SSSP | `cugraph.sssp(G, source=o)` → `[vertex,distance,predecessor]` | `nx.single_source_dijkstra_path_length(G,o,weight="w")` |
| BFS | `cugraph.bfs(G, start=o)` | `nx.single_source_shortest_path_length` |
| **Multi-source skim** | **No native** → loop `sssp` per origin (each GPU-parallel over targets), stack distance cols | `nx.multi_source_dijkstra` / `all_pairs_dijkstra_path_length` |
| Path reconstruction | `predecessor` column | `nx.single_source_dijkstra` returns paths |
cuGraph SSSP rejects negative weights (BPR ≥ t0 > 0, fine). For per-iteration AON: one `sssp` per origin, rebuild trees from `predecessor`, aggregate OD→links via cuDF group-bys. Keep one `backend in {gpu,cpu}` abstraction so the same FW driver calls either.

## Determinism
- Fixed `max_iter` + `rgap_target`; never wall-clock. **Tie-breaking** is the #1 nondeterminism source (equal-cost paths) → break by lowest id or add `+ id·1e-9` cost epsilon (distances are deterministic; *predecessors/paths* are the risk, esp. parallel cuGraph). **float64** for costs/flows; **ordered group-by reductions** not atomics; line search = fixed-iteration bisection. **No Monte-Carlo SUE** — use analytic Dial/path-logit if SUE needed. CPU↔GPU: assert *within tolerance* (~1e-12–1e-9 reduction differences below assignment tolerance).

### Summary
AequilibraE 1.6.2 CPU oracle via `bfw` on TNTP. Implement BPR(0.15/4)+FW→BFW with rgap; Dial/logit for SUE (stretch). **GPU is the one real risk** — cu13 aarch64 wheels exist, sm_120↔121 binary-compatible, but unconfirmed on GB10 → gate behind smoke test, CPU-fallback-first. cuGraph `sssp`/`bfs`, no multi-source (loop per origin); NetworkX mirrors.

### Links
AequilibraE: https://github.com/AequilibraE/aequilibrae · static assignment: https://www.aequilibrae.com/latest/python/static_traffic_assignment.html · VDFs: https://www.aequilibrae.com/latest/python/traffic_assignment/volume_delay_functions.html · cudf-cu13: https://pypi.org/project/cudf-cu13/ · getting cuGraph: https://docs.rapids.ai/api/cugraph/stable/installation/getting_cugraph/ · RAPIDS install: https://docs.rapids.ai/install/ · cugraph.sssp: https://docs.rapids.ai/api/cugraph/stable/api_docs/api/cugraph/cugraph.sssp/ · TNTP networks: https://github.com/bstabler/TransportationNetworks · dgx-spark-setup: https://github.com/natolambert/dgx-spark-setup · sm_121 support thread: https://forums.developer.nvidia.com/t/dgx-spark-sm121-software-support-is-severely-lacking-official-roadmap-needed/357663
