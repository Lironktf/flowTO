"""P14 — Intervention Impact Dataset (real closure/opening → observed-traffic labels).

A phased, test-driven build (clean → spatial → temporal → labels → openings →
confounders → counterfactual → package) that productionizes the v1 cuDF prototype
in ``data/dataset/`` into a tested, importable CPU-first (pandas) pipeline, with a
cuDF parity gate on the GB10. See ``docs/specs/14-closure-dataset.md``.

Cross-cutting invariants (each has a regression test):
  * a "site" is a ``centreline_id`` (an intersection surveyed on many days), NOT a
    ``count_id`` (a single survey day) — joining on count_id silently zeroes baselines.
  * labels are SIGNED (a closure usually lowers volume on the segment, raises it on
    detours) — never assume "closure => more traffic".
  * missing data produces NO row (no fabrication).
"""
