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

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
