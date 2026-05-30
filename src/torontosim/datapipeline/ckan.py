"""CKAN fetchers for the City of Toronto open-data portal.

Pattern (research/01): ``package_show`` lists a package's resources; resolve the
one you want **by format (and optional name substring)** so renames don't break
us; bulk-download via the resource ``url`` or the ``/datastore/dump/<uuid>``
stream; paginate ``datastore_search`` (server-side SQL is disabled).

HTTP is injected (``get_json`` / ``session``) so tests stay hermetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

API_BASE = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action"
DUMP_BASE = "https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump"

JsonGetter = Callable[..., dict[str, Any]]


def _default_get_json(url: str, params: dict | None = None, timeout: int = 60) -> dict[str, Any]:
    import requests

    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def package_show(pkg: str, *, get_json: JsonGetter = _default_get_json) -> dict[str, Any]:
    """Return a package's ``result`` dict (incl. ``resources``)."""
    data = get_json(f"{API_BASE}/package_show", params={"id": pkg})
    return data["result"]


def resolve_resource(
    pkg: str,
    fmt: str,
    *,
    name_contains: str | None = None,
    get_json: JsonGetter = _default_get_json,
) -> dict[str, Any]:
    """Resolve a single resource by format (case-insensitive) + optional name.

    Resolve-by-name survives resource UUID/url renames. Raises ``LookupError``
    if nothing matches.
    """
    resources = package_show(pkg, get_json=get_json).get("resources", [])
    fmt_l = fmt.lower()
    cands = [r for r in resources if (r.get("format") or "").lower() == fmt_l]
    if name_contains:
        nc = name_contains.lower()
        cands = [r for r in cands if nc in (r.get("name") or "").lower()]
    if not cands:
        raise LookupError(
            f"no '{fmt}' resource"
            + (f" matching '{name_contains}'" if name_contains else "")
            + f" in package '{pkg}'"
        )
    return cands[0]


def dump_url(resource_id: str) -> str:
    """Full-CSV dump URL for a datastore resource."""
    return f"{DUMP_BASE}/{resource_id}"


def datastore_pages(
    resource_id: str,
    *,
    limit: int = 10_000,
    get_json: JsonGetter = _default_get_json,
) -> Iterator[dict[str, Any]]:
    """Yield records from a datastore resource, paginating ``datastore_search``."""
    offset = 0
    while True:
        result = get_json(
            f"{API_BASE}/datastore_search",
            params={"id": resource_id, "limit": limit, "offset": offset},
        )["result"]
        records = result.get("records", [])
        yield from records
        offset += limit
        if not records or offset >= result.get("total", 0):
            break


def download_file(url: str, dest, *, session=None, chunk: int = 1 << 20) -> str:
    """Stream a URL to ``dest`` (browser UA; needed by some City endpoints)."""
    import os

    import requests

    sess = session or requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (TorontoSim data pipeline)"}
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    with sess.get(url, headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for block in r.iter_content(chunk_size=chunk):
                if block:
                    fh.write(block)
    return str(dest)
