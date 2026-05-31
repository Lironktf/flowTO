#!/usr/bin/env python3
"""Bake the bylaw RAG corpus from the Toronto Municipal Code (P09).

Downloads the curated Municipal Code chapter PDFs, extracts + cleans their text,
splits them into ``§``-section chunks, and writes each intervention-relevant
section as a small ``.md`` doc into the copilot corpus — with real provenance
(chapter, section number, source URL) so every citation is checkable.

This is a **pre-event bake step**: its output (the corpus ``.md`` files) is
committed, so the demo runs fully offline. Re-run only to refresh the corpus.

    python scripts/bake_bylaws.py            # download + extract + write corpus
    python scripts/bake_bylaws.py --all      # keep every section, not just relevant
    python scripts/bake_bylaws.py --offline  # use the cached PDFs under data/raw/bylaws

Hand-curated summary docs (``ch880_fire_route`` etc.) are preserved untouched —
they stay demo-tuned for the rehearsed prompts; the extracted ``mc*`` docs add
real legal text for off-script questions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW_DIR = os.path.join(REPO, "data", "raw", "bylaws")
CORPUS_DIR = os.path.join(REPO, "src", "torontosim", "copilot", "corpus")
PROVENANCE = os.path.join(REPO, "data", "bylaws_provenance.json")

# Curated Municipal Code chapters. Each is downloaded, sectioned, and the
# intervention-relevant sections are written to the corpus.
MANIFEST = [
    {
        "chapter": "880",
        "title": "Fire Routes",
        "url": "https://www.toronto.ca/legdocs/municode/1184_880.pdf",
        "source": "City of Toronto Municipal Code, Ch. 880 (Fire Routes)",
    },
    {
        "chapter": "950",
        "title": "Traffic and Parking",
        "url": "https://www.toronto.ca/legdocs/municode/1184_950.pdf",
        "source": "City of Toronto Municipal Code, Ch. 950 (Traffic and Parking)",
    },
    {
        "chapter": "937",
        "title": "Temporary Closing of Highways",
        "url": "https://www.toronto.ca/legdocs/municode/1184_937.pdf",
        "source": "City of Toronto Municipal Code, Ch. 937 (Temporary Closing of Highways)",
    },
    {
        "chapter": "886",
        "title": "Footpaths, Pedestrian Ways, Bicycle Paths, Bicycle Lanes and Cycle Tracks",
        "url": "https://www.toronto.ca/legdocs/municode/1184_886.pdf",
        "source": "City of Toronto Municipal Code, Ch. 886 (Bicycle Lanes and Cycle Tracks)",
    },
    {
        "chapter": "743",
        "title": "Streets and Sidewalks, Use of",
        "url": "https://www.toronto.ca/legdocs/municode/1184_743.pdf",
        "source": "City of Toronto Municipal Code, Ch. 743 (Use of Streets and Sidewalks)",
    },
]

# A section is kept in the corpus when its text touches an intervention concept
# (closures, transit, lanes, one-way/contraflow, emergency access, events…).
# This keeps the corpus on-topic; pass --all to keep every prose section.
RELEVANT = re.compile(
    r"\b(clos|reopen|contraflow|one-way|one way|two-way|reserved lane|transit|streetcar|"
    r"bus lane|through|turn|entry prohibit|emergency|fire route|access|detour|lane|"
    r"speed|signal|pedestrian|event|temporary|highway|stop|bicycle|cycle|bike|sidewalk|"
    r"footpath|occupanc|construction|permit|parade|festival|hoarding)\b",
    re.IGNORECASE,
)

_SECTION = re.compile(r"§\s*(\d+-\d+(?:\.\d+)?)\.\s+(.+?)(?=\n|$)")
_HEADER = re.compile(
    r"^(TORONTO MUNICIPAL CODE|CHAPTER \d+,.*|\s*\d+-\d+\s+\w+ \d+,? \d{4}\s*)$",
    re.IGNORECASE,
)


def _download(url: str, dest: str, *, offline: bool) -> None:
    if os.path.exists(dest) and (offline or os.path.getsize(dest) > 0):
        return
    if offline:
        raise FileNotFoundError(f"--offline but no cached PDF at {dest}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "torontosim-bake/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())


def _extract_text(pdf_path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    lines: list[str] = []
    for page in reader.pages:
        for ln in (page.extract_text() or "").splitlines():
            if _HEADER.match(ln.strip()):
                continue  # drop repeated page header / footer
            lines.append(ln.rstrip())
    return "\n".join(lines)


def _is_schedule(secid: str, title: str) -> bool:
    return "schedule" in title.lower()


def _clean_title(title: str) -> str:
    title = re.sub(r"\[(Amended|Added|Repealed|Renumbered)[^\]]*\]?", "", title)
    return re.sub(r"\s+", " ", title).strip().rstrip(".")


def _split_sections(text: str) -> list[tuple[str, str, str]]:
    """Return [(secid, title, body)] split on ``§ NNN-NN. Title.`` markers.

    A section id appears twice: first in the table of contents (clean title, no
    body) then in the body (real text, but its header line may wrap into an
    ``[Amended …]`` note). We take the *first-seen* title and the *longest* body.
    """
    matches = list(_SECTION.finditer(text))
    titles: dict[str, str] = {}
    bodies: dict[str, str] = {}
    for i, m in enumerate(matches):
        secid = m.group(1)
        title = _clean_title(m.group(2))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = re.sub(r"\s+\n", "\n", text[start:end]).strip()
        # Drop an orphaned amendment fragment wrapped off the header line
        # (e.g. a body starting "law 1048-2005] FIRE ROUTE …").
        body = re.sub(r"^\s*(law\s+)?[\d-]*\d\]\s*", "", body)
        # First non-amendment title wins (the clean ToC entry).
        if title and secid not in titles:
            titles[secid] = title
        if secid not in bodies or len(body) > len(bodies[secid]):
            bodies[secid] = body
    return [(sid, titles.get(sid, sid), bodies[sid]) for sid in bodies]


def bake(*, keep_all: bool, offline: bool) -> dict:
    os.makedirs(CORPUS_DIR, exist_ok=True)
    written: list[dict] = []
    for entry in MANIFEST:
        ch = entry["chapter"]
        pdf = os.path.join(RAW_DIR, f"ch{ch}.pdf")
        _download(entry["url"], pdf, offline=offline)
        text = _extract_text(pdf)
        sections = _split_sections(text)
        kept = 0
        for secid, title, body in sections:
            if _is_schedule(secid, title) or len(body) < 120:
                continue  # skip schedules (address tables) + stubs
            if not keep_all and not RELEVANT.search(body):
                continue
            doc_id = f"mc{ch}_{secid.replace('-', '_').replace('.', '_')}"
            full_title = f"Municipal Code § {secid} — {title}"
            source = f"{entry['source']}, § {secid}. {entry['url']}"
            # Trim very long sections to a citation-sized excerpt.
            excerpt = body if len(body) <= 2400 else body[:2400].rsplit(" ", 1)[0] + " […]"
            md = f"# {full_title}\nSource: {source}\n\n{excerpt}\n"
            with open(os.path.join(CORPUS_DIR, f"{doc_id}.md"), "w") as f:
                f.write(md)
            written.append({"doc_id": doc_id, "title": full_title, "section": secid, "url": entry["url"]})
            kept += 1
        print(f"[bake] Ch.{ch} {entry['title']:20} sections={len(sections):>3} kept={kept}")

    os.makedirs(os.path.dirname(PROVENANCE), exist_ok=True)
    with open(PROVENANCE, "w") as f:
        json.dump({"docs": written, "manifest": MANIFEST}, f, indent=2)
    print(f"[bake] wrote {len(written)} extracted section docs -> {CORPUS_DIR}")
    print(f"[bake] provenance -> {PROVENANCE}")
    return {"written": len(written)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Bake the bylaw RAG corpus from the Municipal Code.")
    ap.add_argument("--all", action="store_true", help="keep every prose section, not just relevant")
    ap.add_argument("--offline", action="store_true", help="use cached PDFs under data/raw/bylaws")
    args = ap.parse_args()
    bake(keep_all=args.all, offline=args.offline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
