"""Compatibility shim: ``src.graph`` -> ``torontosim.graph`` (P00 migration).

Liron's tests and ``scripts/train_*.sh`` import ``from src.graph import ...``.
The code now lives in ``torontosim.graph``; this shim re-points the package
``__path__`` so legacy submodule imports (``src.graph.routing`` etc.) keep
resolving. Remove once all call-sites use ``torontosim.*`` (tracked task).
"""

from __future__ import annotations

import torontosim.graph as _pkg

__path__ = _pkg.__path__
__all__ = getattr(_pkg, "__all__", [])

from torontosim.graph import *  # noqa: E402,F401,F403
