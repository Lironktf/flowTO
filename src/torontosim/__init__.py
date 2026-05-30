"""TorontoSim — local-first 3-D Toronto traffic digital twin.

This package consolidates Liron's prototype (``graph``, ``model``,
``simulation``) and the spec's new engines, all importable under the single
``torontosim`` namespace. Legacy ``src.graph`` / ``src.model`` /
``src.simulation`` imports continue to resolve via thin compatibility shims
(see ``src/graph/__init__.py`` et al.) during the P00 migration.
"""

from __future__ import annotations

__version__ = "0.1.0"
