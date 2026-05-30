"""Configurable Ollama transport for the live Nemotron copilot (P09).

Dependency-free (urllib) so it works both on the Spark (``localhost:11434``) and
from a dev box pointing at the Spark over Tailscale. Configuration via env:

* ``TS_OLLAMA_HOST``   — base URL (default ``http://localhost:11434``)
* ``TS_COPILOT_MODEL`` — model tag   (default ``nemotron3:33b``)

Nemotron reasoning models need ``think=False`` + ``format=<schema>`` or the
response comes back empty (verified on the Spark). First call pays a ~11s model
load; ``warmup()`` + ``keep_alive`` hide it after that.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "nemotron3:33b"
KEEP_ALIVE = "10m"


def host() -> str:
    return os.environ.get("TS_OLLAMA_HOST", DEFAULT_HOST).rstrip("/")


def model() -> str:
    return os.environ.get("TS_COPILOT_MODEL", DEFAULT_MODEL)


def available(timeout: float = 5.0) -> bool:
    """True if the Ollama server responds and the configured model is pulled."""
    try:
        with urllib.request.urlopen(host() + "/api/tags", timeout=timeout) as r:
            names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return False
    base = model().split(":")[0]
    return any(base in n for n in names)


def _body(system: str, prompt: str, schema: dict | None, *, stream: bool) -> bytes:
    body = {
        "model": model(),
        "system": system,
        "prompt": prompt,
        "stream": stream,
        "think": False,
        "options": {"temperature": 0},
        "keep_alive": KEEP_ALIVE,
    }
    if schema is not None:
        body["format"] = schema
    return json.dumps(body).encode()


def generate(system: str, prompt: str, schema: dict | None = None, *, timeout: float = 180.0) -> str:
    """One-shot generation → response text. Schema-constrains decoding if given."""
    req = urllib.request.Request(
        host() + "/api/generate",
        data=_body(system, prompt, schema, stream=False),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"]


def stream(system: str, prompt: str, schema: dict | None = None, *, timeout: float = 180.0) -> Iterator[dict]:
    """Yield ``{"token","done","total_ms","first"}`` events as tokens arrive.

    ``first`` is True on the first content token (for the latency HUD). Final
    event has ``done=True`` and ``total_ms`` set from Ollama's timing.
    """
    req = urllib.request.Request(
        host() + "/api/generate",
        data=_body(system, prompt, schema, stream=True),
        headers={"Content-Type": "application/json"},
    )
    first_sent = False
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            evt = json.loads(line)
            tok = evt.get("response", "")
            done = bool(evt.get("done"))
            is_first = bool(tok) and not first_sent
            if is_first:
                first_sent = True
            yield {
                "token": tok,
                "done": done,
                "first": is_first,
                "total_ms": (evt.get("total_duration", 0) // 1_000_000) if done else None,
            }
            if done:
                break


def warmup(timeout: float = 120.0) -> bool:
    """Pre-load the model (pay the cold ~11s once) so the first real ask is fast."""
    try:
        generate("You are a copilot. Reply with the single word: ready.", "ping", timeout=timeout)
        return True
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return False
