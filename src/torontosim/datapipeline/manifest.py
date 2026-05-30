"""Raw-file lineage manifest + attribution strings (research/01).

``data/manifest.json`` records, per fetched raw file: source URL, CKAN resource
UUID, fetch timestamp, sha256, and license — so ``bake`` is offline-repeatable
and the provenance is auditable for the judges.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field

ATTRIBUTION = {
    "toronto": "Contains information licensed under the Open Government Licence – Toronto",
    "ontario": "Contains information licensed under the Open Government Licence – Ontario",
    "eccc": "Contains data from Environment and Climate Change Canada",
}


@dataclass
class ManifestEntry:
    dataset: str
    source_url: str
    resource_uuid: str | None
    fetched_at: str  # ISO-8601 (passed in; no wall-clock here for determinism)
    sha256: str
    license: str
    path: str
    rows: int | None = None


@dataclass
class Manifest:
    entries: list[ManifestEntry] = field(default_factory=list)

    def add(self, entry: ManifestEntry) -> None:
        self.entries.append(entry)

    def to_dict(self) -> dict:
        return {
            "attribution": ATTRIBUTION,
            "datasets": [asdict(e) for e in self.entries],
        }

    def write(self, path) -> str:
        path = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
        return path

    @classmethod
    def load(cls, path) -> "Manifest":
        with open(path) as fh:
            data = json.load(fh)
        m = cls()
        for d in data.get("datasets", []):
            m.add(ManifestEntry(**d))
        return m


def sha256_file(path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()
