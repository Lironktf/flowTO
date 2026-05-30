# Research Brief 03 — OD demand: TTS / Census + IPF calibration

> Feeds **P03**. Decision: seed OD from real survey data, IPF-calibrate to turning counts.

## Access reality (verdict per source)

### 1. TTS — Transportation Tomorrow Survey (DMG / U of T) — **PARTIALLY GATED**
- GTHA household travel survey, every 5 years; latest **TTS 2022** (also 2016, 2011…). Zone system = **GTA06**, **3,764 TAZ**; boundary files public.
- **Gate:** the **Data Retrieval System (iDRS)** needs a **registered account** (`dmg.utoronto.ca/drs-access/`), is an interactive **cross-tab tool (not bulk download)**, and **suppresses cells < 4 observations**. A dense 3,764² matrix is extremely sparse — clean OD only emerges at coarser aggregation. Registration approval is not instant → **risky on a hackathon clock**.
- **✅ OPEN ESCAPE HATCH — use this:** **TTS2016R** (Soukhova & Páez), a **CC BY 4.0** R/data package derived from TTS 2016: **person→jobs OD flows, worker+job counts per TAZ, GTA06 boundaries, car travel-time skims** — no login. Home→work 2016, but an excellent seed. → https://soukhova.github.io/TTS2016R/

### 2. Fallback A — StatsCan 2021 commuting flows — **OPEN, coarse**
- Table **`98-10-0459-01`** (residence→workplace by CSD): free CSV. → https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901
- **Limit:** down to **Census Subdivision** (municipality) only — intra-Toronto is one giant cell. Tract/DA OD = custom paid order. Use for regional/external inflows + IPF marginals, not intra-city distribution.

### 3. Fallback B — synthetic gravity (population × employment) — **OPEN, recommended primary**
- **Population:** StatsCan 2021 by **DA/Census Tract** (open) + boundary files.
- **Employment:** **City of Toronto Employment Survey** (summary tables on Open Data) → https://www.toronto.ca/city-government/data-research-maps/research-reports/planning-development/toronto-employment-survey/ ; or Census place-of-work by DA/CT. TTS2016R also ships **job counts per TAZ** (ready attractions vector).
- **Verdict:** most reliable for a hackathon — all open/instant; only need *counts* (which we have) to calibrate.

## Recommended pipeline (seed → calibrate)
**Seed:** (1) best = TTS2016R TAZ OD + car skim; (2) most robust = synthetic gravity from Census population (`P_i`) + Employment Survey jobs (`A_j`) with skim; (3) StatsCan CSD flows as regional marginals/sanity.
**Calibrate:** Stage 1 = **Furness/IPF** to production/attraction marginals; Stage 2 = **ODME** so assigned link/turn volumes match observed TMC counts (under-determined — regularize to the seed). **Time-of-day:** factor daily → AM/PM peaks.

## Methods + libraries
**Gravity (doubly-constrained):** `T_ij = A_i·O_i·B_j·D_j·f(c_ij)`, `f` = deterrence (`exp(-β c)` / `c^-β` / gamma); `A_i,B_j` balancing factors solved iteratively (= Furness). Calibrate `β` to match observed mean trip length.
**IPF/Furness libs:** `ipfn` (https://github.com/harisbal/ipfn) — N-dim IPF; seed + target margins, `.iteration()`. **AequilibraE** has `GravityCalibration` (EXPO/POWER/GAMMA), `GravityApplication`, `Ipf` — plus assignment, so it can do seed→assign→compare-counts in one stack: https://www.aequilibrae.com/docs/python/V.1.1.0/_auto_examples/trip_distribution/plot_trip_distribution.html
**ODME (counts → OD):** name = **OD Matrix Estimation** (Cascetta & Nguyen GLS; Spiess gradient; Bell). Structurally **under-determined** (N² OD pairs ≫ M counts) → resolve by regularizing to the seed + many screenlines. Turning counts enter as linear constraints on path flows. Algorithms: **SPSA/c-SPSA**, Spiess gradient, path-flow estimator. Refs: Cascetta&Nguyen https://pubsonline.informs.org/doi/10.1287/trsc.27.4.363 ; c-SPSA https://www.sciencedirect.com/science/article/abs/pii/S0968090X15000248 . **Hackathon pragmatic:** assign seed OD to paths once, then **IPF on path/turn flows** treating observed turning counts as marginals — the cheap under-determined version, reuses `ipfn`.
**Time-of-day factors (defaults if not deriving from TTS):** AM peak-hour ≈ 8–10% of daily; PM ≈ 9–11% (PM usually higher); peak period AM ~20–25%, PM ~25–30%; K-factor ≈ 0.08–0.10; directional AM ~65/35 inbound, PM reverse.

## Bottom line for the spec
1. **Seed** with TTS2016R (open, real, GTA06 + skims + jobs) OR Census-pop × Employment gravity.
2. **Stage-1** IPF (`ipfn`/AequilibraE `Ipf`) to P/A marginals.
3. **Stage-2** ODME to TMC counts (AequilibraE assignment + Spiess/SPSA if time; else IPF-on-turn-flows).
4. **Factor** to AM/PM.
5. TTS iDRS + tract-level custom orders = optional refinements, not blockers.

**Gated:** TTS iDRS, StatsCan tract/DA OD. **Open & instant:** TTS2016R, StatsCan CSD flows, Census pop by DA/CT, Employment Survey, GTA06 boundaries, all Python tooling.

### Links
DMG: https://dmg.utoronto.ca/tts-introduction/ · TTS2016R: https://soukhova.github.io/TTS2016R/ · StatsCan 98-10-0459-01: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045901 · Employment Survey: https://www.toronto.ca/city-government/data-research-maps/research-reports/planning-development/toronto-employment-survey/ · ipfn: https://github.com/harisbal/ipfn · AequilibraE distribution: https://www.aequilibrae.com/docs/python/V.1.1.0/_auto_examples/trip_distribution/plot_trip_distribution.html
