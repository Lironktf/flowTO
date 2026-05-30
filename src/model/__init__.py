"""Compatibility shim: ``src.model`` -> ``torontosim.model`` (P00 migration).

See ``src/graph/__init__.py`` for rationale. Remove once call-sites use
``torontosim.*``.
"""

from __future__ import annotations

import torontosim.model as _pkg

__path__ = _pkg.__path__
__all__ = getattr(_pkg, "__all__", [])

from torontosim.model import *  # noqa: E402,F401,F403
