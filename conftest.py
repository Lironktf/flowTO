"""Pytest path bootstrap.

Makes the package importable two ways during the P00 migration:
  * ``torontosim``      — the real package, located under ``src/``.
  * ``src.graph`` etc.  — legacy compatibility shims at the repo root.

This keeps tests runnable without requiring ``pip install -e .`` first, while
the editable install (pyproject) remains the production path.
"""

from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --------------------------------------------------------------------------- #
# `@pytest.mark.network` tests hit live sources (City of Toronto, Metrolinx).
# They are SKIPPED by default (so CI's `pytest -q -m "not spark"` stays green on
# the air-gapped runner) and opt-in via `--run-network` — run on the Spark /
# pre-event where the network + disk are available.
# --------------------------------------------------------------------------- #
def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run @pytest.mark.network tests (live downloads; Spark/pre-event)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip_network = pytest.mark.skip(reason="network test; pass --run-network (or run on Spark)")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
