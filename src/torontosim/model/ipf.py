"""Stage-1 IPF / Furness balancing (P03).

Biproportional fitting of a seed matrix to row (production) and column
(attraction) marginals. Pure NumPy for determinism and zero extra deps (``ipfn``
is a heavier optional alternative). Structural zeros in the seed stay zero.
"""

from __future__ import annotations

import numpy as np


def ipf(
    seed: np.ndarray,
    row_marginals: np.ndarray,
    col_marginals: np.ndarray,
    *,
    max_iter: int = 1000,
    tol: float = 1e-9,
) -> np.ndarray:
    """Fit ``seed`` to the given marginals via iterative proportional fitting.

    Marginals should sum to (approximately) the same total; if they differ the
    column marginals are rescaled to the row total so the fit can converge.
    Deterministic: same inputs -> identical output.
    """
    seed = np.asarray(seed, dtype=np.float64)
    row_marginals = np.asarray(row_marginals, dtype=np.float64)
    col_marginals = np.asarray(col_marginals, dtype=np.float64)

    if seed.ndim != 2:
        raise ValueError("seed must be 2-D")
    if seed.shape[0] != row_marginals.size or seed.shape[1] != col_marginals.size:
        raise ValueError("marginal sizes must match seed dimensions")

    row_total = row_marginals.sum()
    col_total = col_marginals.sum()
    if col_total > 0 and not np.isclose(row_total, col_total):
        col_marginals = col_marginals * (row_total / col_total)

    mat = seed.copy()
    for _ in range(max_iter):
        # Row fit.
        row_sums = mat.sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            rscale = np.where(row_sums > 0, row_marginals / row_sums, 0.0)
        mat = mat * rscale[:, None]
        # Column fit.
        col_sums = mat.sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            cscale = np.where(col_sums > 0, col_marginals / col_sums, 0.0)
        mat = mat * cscale[None, :]

        # Convergence: row marginals satisfied (cols may lag by one half-step).
        if np.max(np.abs(mat.sum(axis=1) - row_marginals)) < tol:
            break
    return mat
