"""Resolve typed intersection names to graph nodes and the road between them.

The copilot lets a user say "close the road from <intersection X> to
<intersection Y>". The LLM only extracts the two *names*; this module does the
exact graph work (no hallucinated edge ids): fuzzy-match each name to a node by
its synthesized ``name`` (e.g. "Don Mills Road & York Mills Road"), then take the
shortest path between them and return the edges on it.
"""

from __future__ import annotations

import difflib


def _norm(s) -> str:
    """Lowercase, unify '&'/'and'/'/', collapse whitespace."""
    s = str(s or "").lower().replace("&", " and ").replace("/", " ")
    return " ".join(s.split())


def _tokens(s: str) -> set:
    # Drop the connective 'and' and short tokens (st, rd handled as substrings).
    return {t for t in _norm(s).split() if t != "and" and len(t) > 2}


# Generic road-type / directional words that are NOT distinctive on their own — a
# match driven only by these (e.g. 'Narnia Expressway' -> 'Gardiner Expressway' via
# the shared word 'expressway') is a false positive: the real name token never matched.
_GENERIC_ROAD_WORDS = {
    "street",
    "road",
    "avenue",
    "expressway",
    "boulevard",
    "drive",
    "lane",
    "way",
    "court",
    "crescent",
    "trail",
    "parkway",
    "highway",
    "circle",
    "place",
    "gardens",
    "square",
    "terrace",
    "north",
    "south",
    "east",
    "west",
    "the",
}


def _distinctive(tokens: set) -> set:
    """The name-carrying tokens — generic road-type/directional words removed."""
    return {t for t in tokens if t not in _GENERIC_ROAD_WORDS}


# Road-class prominence (higher = more major), for tiebreaking ambiguous name matches.
_CLASS_RANK = {
    "motorway": 6,
    "trunk": 5,
    "primary": 4,
    "secondary": 3,
    "tertiary": 2,
    "residential": 1,
    "unclassified": 1,
}


def resolve_node_by_name(graph, name, *, min_score: float = 1.1):
    """Best node whose ``name`` matches ``name``. Returns (node_id, name, score) or None.

    Scores by query-token overlap (how many of the typed street words appear in
    the node name) plus a fuzzy string ratio, so "yonge bloor", "Yonge & Bloor",
    and "yonge and bloor st" all land on the same intersection.
    """
    q = _norm(name)
    q_tokens = _tokens(name)
    if not q or not q_tokens:
        return None

    best = None
    best_score = -1.0
    for node, data in graph.nodes(data=True):
        nm = data.get("name")
        if not nm:
            continue
        nn = _norm(nm)
        overlap = len(q_tokens & _tokens(nm)) / len(q_tokens)
        ratio = difflib.SequenceMatcher(None, q, nn).ratio()
        score = overlap * 2.0 + ratio  # overlap dominates; ratio breaks ties
        if score > best_score:
            best_score, best = score, (node, nm, score)

    if best and best[2] >= min_score:
        return best
    return None


def road_edges_by_name(graph, road_name) -> dict:
    """All open edges of the road whose name best matches ``road_name``.

    For "close all of Gardiner Expressway" — fuzzy-match the typed name to the
    closest distinct road name in the graph, then return every open edge on it.
    ``{"found": bool, "road_name": str, "edge_ids": [...], "reason": str}``.
    """
    q = _norm(road_name)
    q_tokens = _tokens(road_name)
    if not q or not q_tokens:
        return {"found": False, "reason": "no road name given"}

    # Most-prominent road_class per distinct name → a small tiebreak bonus so an
    # ambiguous match (e.g. "Gardiner" → Expressway vs Road) prefers the major road.
    name_rank: dict = {}
    for _u, _v, d in graph.edges(data=True):
        nm = d.get("road_name")
        if not nm:
            continue
        r = _CLASS_RANK.get(d.get("road_class") or "", 0)
        if r > name_rank.get(nm, -1):
            name_rank[nm] = r

    # Rank by (token overlap, then road prominence, then fuzzy ratio). Prominence
    # outranks the length-biased ratio so equal-overlap matches prefer the major
    # road (e.g. "Gardiner" → Expressway/motorway, not the residential Road).
    best = None
    best_key = (-1.0, -1, -1.0)
    best_base = 0.0
    for nm, rank in name_rank.items():
        nn = _norm(nm)
        overlap = len(q_tokens & _tokens(nm)) / len(q_tokens)
        ratio = difflib.SequenceMatcher(None, q, nn).ratio()
        key = (overlap, rank, ratio)
        if key > best_key:
            best_key, best, best_base = key, nm, overlap * 2.0 + ratio

    if best is None or best_base < 1.0:
        return {"found": False, "reason": f"no road matching {road_name!r}"}

    # Reject false positives that match only on a generic word: if the query has a
    # distinctive name token (e.g. 'narnia'), the matched road must share one of them.
    # Otherwise 'Narnia Expressway' would resolve to 'Gardiner Expressway' on 'expressway'
    # alone. (If the query is ONLY generic words, skip the gate and keep the best match.)
    distinctive_q = _distinctive(q_tokens)
    if distinctive_q and not (distinctive_q & _distinctive(_tokens(best))):
        return {"found": False, "reason": f"no road matching {road_name!r}"}

    edge_ids = [
        d.get("edge_id")
        for _u, _v, d in graph.edges(data=True)
        if d.get("road_name") == best and d.get("status") != "closed" and d.get("edge_id")
    ]
    if not edge_ids:
        return {"found": False, "reason": f"{best!r} has no open segments"}
    return {"found": True, "road_name": best, "edge_ids": edge_ids}


def road_between(graph, from_name, to_name) -> dict:
    """Resolve two intersection names and return the edges on the road between.

    ``{"found": bool, "from_node", "to_node", "from_name", "to_name",
       "edge_ids": [...], "reason": str}``. Reuses ``routing.find_shortest_path``
    so closed edges are skipped and the result is exact.
    """
    from ..graph.routing import find_shortest_path

    a = resolve_node_by_name(graph, from_name)
    if a is None:
        return {"found": False, "reason": f"couldn't find intersection {from_name!r}"}
    b = resolve_node_by_name(graph, to_name)
    if b is None:
        return {"found": False, "reason": f"couldn't find intersection {to_name!r}"}
    if a[0] == b[0]:
        return {"found": False, "reason": "both names resolved to the same intersection"}

    path = find_shortest_path(graph, a[0], b[0])
    if not path.get("found") or not path.get("edges"):
        return {
            "found": False,
            "reason": f"no drivable route between {a[1]!r} and {b[1]!r}",
        }

    return {
        "found": True,
        "from_node": a[0],
        "to_node": b[0],
        "from_name": a[1],
        "to_name": b[1],
        "edge_ids": list(path["edges"]),
        "total_distance_m": path.get("total_distance_m"),
    }
