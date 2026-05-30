"""Find a reliable way to get scenario-edit JSON out of a *reasoning* Nemotron model.

Tries several strategies and reports which produce valid JSON, with latency.
"""
import json
import sys
import time
import urllib.request

MODEL = sys.argv[1] if len(sys.argv) > 1 else "nemotron3:33b"
OLLAMA = "http://localhost:11434/api/generate"

SYSTEM = (
    "You are a Toronto city-planning copilot. Convert the planner's request into a JSON "
    "scenario edit with keys: action, target, params, rationale. "
    "Valid actions: close_link, reduce_lanes, add_construction, scale_demand, add_transit_frequency."
)
PROMPT = "Close the Gardiner Expressway eastbound near BMO Field for a World Cup match and explain why."


def call(label, **overrides):
    body = {
        "model": MODEL,
        "system": SYSTEM,
        "prompt": PROMPT,
        "stream": False,
        "options": {"temperature": 0.2},
        "keep_alive": "10m",
    }
    body.update(overrides)
    t = time.time()
    req = urllib.request.Request(
        OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.loads(r.read())
    dt = time.time() - t
    keys = list(resp.keys())
    text = resp.get("response", "")
    thinking = resp.get("thinking", "")
    print(f"\n===== {label}  ({dt:.1f}s) =====")
    print("top-level keys:", keys)
    print("thinking field present:", bool(thinking), f"({len(thinking)} chars)" if thinking else "")
    print("response len:", len(text))
    # try to extract json from response
    parsed = try_parse(text)
    print("response is valid JSON:", parsed is not None)
    if parsed:
        print(json.dumps(parsed, indent=2)[:600])
    else:
        print("response preview:", repr(text[:300]))


def try_parse(text):
    text = text.strip()
    # strip code fences
    if "```" in text:
        text = text.split("```")[1].replace("json", "", 1).strip() if text.count("```") >= 2 else text
    # grab first {...} block
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        text = text[s : e + 1]
    try:
        return json.loads(text)
    except Exception:
        return None


# Strategy 1: format=json (the one that failed) -- baseline
call("S1: format=json", format="json")
# Strategy 2: think disabled, no forced format (parse JSON from text)
call("S2: think=False, free text")
# Strategy 3: think disabled + format=json
call("S3: think=False + format=json", think=False, format="json")
# Strategy 4: thinking allowed, free text, extract JSON block
call("S4: think=True, extract JSON from text", think=True)
