"""LLM smoke test: hit the local Ollama HTTP API (no TTY spinner) and check structured output.

Tests that Nemotron can turn a planner's natural-language request into a scenario-edit JSON
blob -- the core of the copilot (Layer 2).
"""
import json
import sys
import urllib.request

MODEL = sys.argv[1] if len(sys.argv) > 1 else "nemotron3:33b"
OLLAMA = "http://localhost:11434/api/generate"

SYSTEM = (
    "You are a Toronto city-planning copilot. Convert the planner's request into a JSON "
    "scenario edit. Respond ONLY with JSON matching this schema: "
    '{"action": str, "target": str, "params": object, "rationale": str}. '
    "Valid actions: close_link, reduce_lanes, add_construction, scale_demand, add_transit_frequency."
)
PROMPT = "Close the Gardiner Expressway eastbound near BMO Field for a World Cup match and explain why."

# CANONICAL RECIPE for structured output from a *reasoning* Nemotron model:
#   think=False + format=json  -> clean JSON in ~1.8s, no hidden thinking channel.
# (With thinking ON, format=json yields an EMPTY response field -- see scripts/llm_debug.py.)
body = {
    "model": MODEL,
    "system": SYSTEM,
    "prompt": PROMPT,
    "stream": False,
    "think": False,
    "format": "json",
    "options": {"temperature": 0.2},
    "keep_alive": "10m",
}

req = urllib.request.Request(
    OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=300) as r:
    resp = json.loads(r.read())

print("model:", resp.get("model"))
print("load_ms:", resp.get("load_duration", 0) // 1_000_000)
print("eval_ms:", resp.get("eval_duration", 0) // 1_000_000)
print("--- raw response ---")
text = resp["response"]
print(text)
print("--- parsed ---")
try:
    print(json.dumps(json.loads(text), indent=2))
    print("STRUCTURED OUTPUT: OK")
except Exception as e:
    print("parse failed:", e)
