"""Single intent classifier (P09 routing redesign).

ONE constrained Nemotron call is the sole authority on what the user wants — it
replaces the frontend ``isQuestion`` regex *and* the backend ``_COMMAND_HINTS``
keyword cascade, which disagreed and misrouted (a closure phrased as a question
went to free chat; a natural congestion question never reached the grounded
reader). The model classifies the intent and extracts only the NAMES it sees;
``resolve.py`` does the exact graph work, so no edge_id is ever invented.

``mode`` is derived from ``intent`` and tells the frontend which surface to use:
``agent`` (multi-step loop), ``chat`` (token stream), or ``plan`` (a ToolCall
against the scenario API, including grounded data answers like congestion).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError

from . import ollama_client

ModelCall = Callable[[str, str, dict], str]

# Fine-grained intents. close/reopen + segment + capacity resolve deterministically
# via resolve.py; query_congestion reads the baseline; optimize calls P10; focus is
# a read-only camera move; investigate escalates to the agent loop; chat is anything
# conversational (greetings, "what can you do", open questions).
Intent = Literal[
    "close_road",
    "reopen_road",
    "close_segment",
    "reopen_segment",
    "change_capacity",
    "query_congestion",
    "explain",
    "inspect",
    "optimize",
    "mitigate",
    "focus",
    "set_time",
    "investigate",
    "chat",
]

# Which frontend surface handles each intent. Everything that needs the live graph
# or proposes an action goes through "plan"; only true small talk streams as "chat".
_AGENT_INTENTS = {"investigate"}
_CHAT_INTENTS = {"chat"}


class ClassifyResult(BaseModel):
    intent: Intent = "chat"
    road_name: str = ""
    from_intersection: str = ""
    to_intersection: str = ""
    multiplier: Optional[float] = None
    minute: Optional[int] = None  # set_time: minute-of-day 0–1440

    @property
    def mode(self) -> Literal["agent", "chat", "plan"]:
        if self.intent in _AGENT_INTENTS:
            return "agent"
        if self.intent in _CHAT_INTENTS:
            return "chat"
        return "plan"


_SYSTEM = (
    "Classify a Toronto city-planning request into ONE intent and extract the names it "
    "mentions. Return JSON only.\n"
    "Intents:\n"
    "  close_road / reopen_road — act on an ENTIRE named road; put it in 'road_name' "
    "(e.g. 'Gardiner Expressway', 'Yonge Street').\n"
    "  close_segment / reopen_segment — act only BETWEEN two intersections; put them in "
    "'from_intersection' and 'to_intersection' (e.g. 'King & Bathurst').\n"
    "  change_capacity — scale a road's capacity; set 'road_name' and 'multiplier' "
    "(0.5 = halve, 1.5 = +50%).\n"
    "  query_congestion — asks where traffic is worst / busiest right now.\n"
    "  explain — asks WHY a specific named road is congested; put it in 'road_name'.\n"
    "  inspect — asks for stats/details about a named road (capacity, lanes, load); put it in 'road_name'.\n"
    "  optimize — asks for the best / recommended plan (let the optimizer decide).\n"
    "  mitigate — asks to ease / relieve congestion near a place; put the place in 'road_name'.\n"
    "  focus — asks to SHOW / zoom / fly to a place on the map (no change); put it in 'road_name'.\n"
    "  set_time — asks to view a specific time of day OR a named rush/peak period; put the "
    "minute-of-day (0-1440) in 'minute'. Map common phrases: 'morning rush'/'morning peak'=480, "
    "'rush hour'/'evening rush'/'evening peak'/'PM peak'=1020, 'noon'/'midday'=720, 'overnight'=180. "
    "'show rush hour' is set_time (NOT focus).\n"
    "  investigate — a compound or multi-step request ('figure out why X and propose a fix').\n"
    "  chat — greetings, small talk, or a general question not about changing the network.\n"
    "Phrasing and punctuation do NOT matter: 'close King St' and 'can you close King St?' are both "
    "close_road. A question word does not force 'chat' — classify by what the user wants done.\n"
    "For 'road_name', extract the road EXACTLY as the user said it — do NOT append 'Road', 'Street', "
    "or 'Avenue' if they didn't (e.g. 'the Gardiner' -> 'Gardiner', not 'Gardiner Road')."
)


def classify_schema() -> dict:
    return ClassifyResult.model_json_schema()


def _default_model_call(system: str, prompt: str, schema: dict) -> str:
    return ollama_client.generate(system, prompt, schema)


def classify(
    prompt: str, *, history: str = "", model_call: ModelCall | None = None
) -> ClassifyResult:
    """Classify ``prompt`` into one intent + entities. ``history`` (recent
    conversation, oldest→newest) lets the model resolve referential phrases like
    'the worst road', 'that road', 'it', or 'reopen it' to a concrete road name.
    Falls back to ``chat`` on any model/parse failure."""
    model_call = model_call or _default_model_call
    text = prompt or ""
    if history.strip():
        text = (
            "Recent conversation (resolve references like 'the worst road', "
            "'that road', 'it' from this — put the ACTUAL road name in 'road_name'):\n"
            f"{history.strip()}\n\nRequest: {prompt}"
        )
    try:
        raw = model_call(_SYSTEM, text, classify_schema())
        return ClassifyResult.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, OSError, ValueError, KeyError):
        return ClassifyResult(intent="chat")
