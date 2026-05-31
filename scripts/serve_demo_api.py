#!/usr/bin/env python
"""Demo API launcher with configurable port + OD size.

For the shared Spark: run off the default :8000 so it coexists with another
server, and use a smaller OD for a fast baseline warm.

  PORT          listen port (default 8010)
  TS_MAX_PAIRS  baseline OD pair count (default 2000 — fast warm; 12000 = full)
  TS_BACKEND    cpu | gpu (cuGraph)

Import the package via PYTHONPATH=<repo>/src so this does NOT re-point a shared
editable install (leaving any other server on the box untouched).
"""

from __future__ import annotations

import os

import uvicorn

from torontosim.api._bootstrap import load_default_state
from torontosim.api.app import create_app

PORT = int(os.environ.get("PORT", "8010"))
MAX_PAIRS = int(os.environ.get("TS_MAX_PAIRS", "2000"))

app = create_app(load_default_state(max_pairs=MAX_PAIRS))
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
