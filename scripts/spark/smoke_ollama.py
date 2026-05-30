"""Ollama / Nemotron smoke test — the gate for the copilot phase (P09).

Hits the local Ollama HTTP API on the Spark and checks that the model returns
valid JSON for a planner request (the core copilot contract). Prints exactly
one verdict token on the last line:

    OLLAMA_OK        -> model served and returned parseable JSON.
    OLLAMA_NO_MODEL  -> server up but the requested model isn't pulled.
    OLLAMA_DOWN      -> server unreachable.

Usage on the Spark:
    scripts/spark/run.sh "python scripts/spark/smoke_ollama.py [model]"

Canonical recipe (from scripts/llm_smoke.py): think=False + format=json yields
clean JSON from a reasoning Nemotron model. A non-OK verdict is not a build
failure — the copilot falls back to canned/mocked results for the demo.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

OLLAMA = "http://localhost:11434"
DEFAULT_MODEL = "nemotron3:33b"

SYSTEM = (
    "You are a Toronto city-planning copilot. Convert the planner's request into a JSON "
    "scenario edit. Respond ONLY with JSON matching: "
    '{"action": str, "target": str, "params": object, "rationale": str}.'
)
PROMPT = "Close the Gardiner Expressway eastbound near BMO Field for a World Cup match."


def _post(path: str, body: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        OLLAMA + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

    # 1) Is the server up? (cheap GET)
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=10) as r:
            tags = json.loads(r.read())
    except (urllib.error.URLError, OSError) as exc:
        print(f"ollama unreachable: {exc!r}", file=sys.stderr)
        print("OLLAMA_DOWN")
        return 0

    names = [m.get("name", "") for m in tags.get("models", [])]
    print("models available:", names)
    if not any(model.split(":")[0] in n for n in names):
        print(f"requested model '{model}' not pulled (have: {names})", file=sys.stderr)
        print("OLLAMA_NO_MODEL")
        return 0

    # 2) Structured-output generation.
    try:
        resp = _post(
            "/api/generate",
            {
                "model": model,
                "system": SYSTEM,
                "prompt": PROMPT,
                "stream": False,
                "think": False,
                "format": "json",
                "options": {"temperature": 0.2},
                "keep_alive": "10m",
            },
        )
        text = resp["response"]
        parsed = json.loads(text)
        print("eval_ms:", resp.get("eval_duration", 0) // 1_000_000)
        print(json.dumps(parsed, indent=2))
        assert "action" in parsed
        print("OLLAMA_OK")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"generation/parse failed: {exc!r}", file=sys.stderr)
        print("OLLAMA_NO_MODEL")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
