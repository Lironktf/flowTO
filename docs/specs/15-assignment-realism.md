# 15 — Traffic-assignment realism (why "the worst road" looks dumb)

Status: **investigation / not yet fixed**. Found during a live copilot audit
(2026-05-31). The copilot's *routing* is correct; the *numbers* it reports are
not, and that makes it look dumb (e.g. "Congestion is worst on Browning Avenue,
v/c 16.9" — a residential side street at a physically impossible volume/capacity
ratio, load 53,962 vs capacity ~400).

## Symptom

On the demo baseline (`TS_MAX_PAIRS=2000`), the single most-congested road is a
short **residential** street at **v/c ≈ 16**, and the optimizer "finds no action
that improves on doing nothing." Both are artifacts of how demand is assigned,
not copilot bugs.

## Root cause (three compounding factors)

1. **All-or-nothing top-k assignment, not user equilibrium.**
   `store.baseline()` runs `simulate_traffic(..., congestion_model="bpr")` but
   leaves `engine="kpath"` (the default). `_kpath_loop`
   (`simulation/simulate_traffic.py`) assigns each OD bundle onto its top-k=3
   shortest paths by *time*, re-routing over 4 iterations. Capacity never enters
   the path-choice cost, so a low-capacity residential shortcut that happens to
   sit on many shortest paths piles up — 4 iterations of BPR penalty isn't
   enough to push the funnelled flow off it (and if the street is a bridge edge
   for those bundles, there's no alternate at all). A true **`equilibrium`**
   engine (BPR + Frank-Wolfe) already exists in the codebase
   (`_run_equilibrium` / `simulation/equilibrium.py`) and spreads flow until no
   cheaper path remains — it would not leave a residential street at v/c 16.

2. **Calibration fixes only the *mean*.** `_calibrate_trips` scales total trips
   so the *mean* loaded-edge v/c ≈ `DEFAULT_TARGET_PRESSURE = 0.55`. The tail is
   unbounded: concentrated links sail past v/c 1 while the average looks healthy.

3. **`max_pairs=2000` concentrates demand.** `generate_od_matrix` scales the OD
   to `NOMINAL_TOTAL_TRIPS = 100_000` regardless of `max_pairs`, then keeps only
   the strongest `max_pairs` pairs. With 2000 pairs that's ~50 trips/pair on a
   thin backbone, so shared links overload. The full 12k spreads the same 100k
   over more routes and the per-link tail drops.

Note `generate_od_matrix` already weights trip *endpoints* down for residential
nodes (`_RANK_ENDPOINT_FACTOR[1] = 0.5`) so trips start/end on arterials — but
that does nothing about residential streets appearing mid-*path*, which is where
the funnel happens.

## Options (cheapest → most principled)

- **A. Bump `max_pairs`** (e.g. 6k–12k). Spreads demand, smaller tail. Cost:
  slower baseline warm (minutes on the contended Spark). Pure config.
- **B. Switch the baseline to the `equilibrium` engine.** Principled fix —
  capacity-aware UE removes the funnel by construction. Cost: Frank-Wolfe is
  slower than the k-path loop; needs a wall-clock check at full graph size, and
  the scenario path (`simulate_scenario`) would want the same engine for
  apples-to-apples compares.
- **C. Generalized path cost in the k-path loop** (time + a capacity/volume
  penalty) so AON avoids overloading thin links. Cheaper than full UE, heuristic.
- **D. Cap/clip reported v/c in the copilot answers.** Cosmetic only — hides the
  artifact, doesn't fix the assignment. Not recommended as the sole fix.

Recommended: **B** for correctness (it already exists — wire `engine="equilibrium"`
into `store.baseline()`/`blast_baseline()` and benchmark), with **A** as the
quick demo-day lever if the warm time is acceptable.
