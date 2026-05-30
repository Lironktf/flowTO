"""Local RAG over a small curated bylaw corpus (P09).

Default retriever is a dependency-free TF-style bag-of-words cosine — fully
offline + deterministic, good enough for a tiny curated corpus. When the ``ai``
extra is installed (Spark), ``sentence-transformers`` embeddings can be swapped
in, but the keyword retriever is the demo-safe path.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass

_CORPUS_DIR = os.path.join(os.path.dirname(__file__), "corpus")
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Doc:
    doc_id: str
    title: str
    source: str
    text: str


def load_corpus(corpus_dir: str | None = None) -> list[Doc]:
    docs: list[Doc] = []
    d = corpus_dir or _CORPUS_DIR
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        text = open(os.path.join(d, fn)).read()
        lines = text.splitlines()
        title = lines[0].lstrip("# ").strip() if lines else fn
        source = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("Source:")), "")
        docs.append(Doc(doc_id=fn[:-3], title=title, source=source, text=text))
    return docs


class Retriever:
    """Bag-of-words cosine retriever with IDF weighting."""

    def __init__(self, docs: list[Doc]):
        self.docs = docs
        self._tf: list[dict] = []
        df: dict = {}
        for doc in docs:
            counts: dict = {}
            for t in _tokens(doc.text):
                counts[t] = counts.get(t, 0) + 1
            self._tf.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1
        n = max(1, len(docs))
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}

    def _vec(self, counts: dict) -> dict:
        return {t: c * self._idf.get(t, 1.0) for t, c in counts.items()}

    def query(self, text: str, k: int = 4) -> list[tuple[Doc, float]]:
        q_counts: dict = {}
        for t in _tokens(text):
            q_counts[t] = q_counts.get(t, 0) + 1
        qv = self._vec(q_counts)
        qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
        scored: list[tuple[Doc, float]] = []
        for doc, counts in zip(self.docs, self._tf):
            dv = self._vec(counts)
            dot = sum(qv.get(t, 0.0) * v for t, v in dv.items())
            dn = math.sqrt(sum(v * v for v in dv.values())) or 1.0
            scored.append((doc, dot / (qn * dn)))
        scored.sort(key=lambda x: (-x[1], x[0].doc_id))
        return scored[:k]


_DEFAULT: Retriever | None = None


def default_retriever() -> Retriever:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Retriever(load_corpus())
    return _DEFAULT


def retrieve(query: str, k: int = 4) -> list[dict]:
    """Top-k bylaw chunks for a query → [{doc_id, title, source, score}]."""
    return [
        {"doc_id": d.doc_id, "title": d.title, "source": d.source, "score": round(s, 4)}
        for d, s in default_retriever().query(query, k)
    ]
