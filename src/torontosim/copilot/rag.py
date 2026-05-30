"""Local RAG over the curated + extracted bylaw corpus (P09).

Two retrievers, same interface:

* ``Retriever`` — dependency-free TF-IDF bag-of-words cosine. Fully offline,
  deterministic. The fallback + the local/CI default.
* ``EmbeddingRetriever`` — ``sentence-transformers`` (all-MiniLM-L6-v2) +
  in-memory cosine. Activates on the Spark (``ai`` extra) where off-script
  prompts benefit from semantic matching. The corpus is ~50 short section docs,
  so an in-process embedding matrix beats standing up Chroma/FAISS — no external
  store, no extra failure mode.

``default_retriever()`` picks embeddings when available (``TS_RAG_BACKEND=auto``,
the default) and degrades to TF-IDF otherwise. Override with ``TS_RAG_BACKEND``
= ``embed`` | ``tfidf`` | ``auto``.
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


_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingRetriever:
    """Semantic retriever: sentence-transformers embeddings + in-memory cosine.

    Raises ``ImportError`` at construction if the ``ai`` extra isn't installed,
    so ``default_retriever()`` can fall back cleanly.
    """

    def __init__(self, docs: list[Doc], model_name: str = _EMBED_MODEL):
        import numpy as np  # noqa: F401 — provided by the ai extra
        from sentence_transformers import SentenceTransformer

        self.docs = docs
        self._np = np
        self._model = SentenceTransformer(model_name)
        mat = self._model.encode(
            [f"{d.title}\n{d.text}" for d in docs], normalize_embeddings=True
        )
        self._mat = np.asarray(mat, dtype="float32")

    def query(self, text: str, k: int = 4) -> list[tuple[Doc, float]]:
        np = self._np
        q = np.asarray(
            self._model.encode([text], normalize_embeddings=True), dtype="float32"
        )[0]
        sims = self._mat @ q  # cosine (rows already L2-normalized)
        order = np.argsort(-sims)[:k]
        return [(self.docs[i], float(sims[i])) for i in order]


_DEFAULT: object | None = None


def _build_retriever():
    backend = os.environ.get("TS_RAG_BACKEND", "auto").lower()
    docs = load_corpus()
    if backend in ("auto", "embed"):
        try:
            return EmbeddingRetriever(docs)
        except Exception:  # noqa: BLE001 — ai extra absent or model unavailable
            if backend == "embed":
                raise
    return Retriever(docs)


def default_retriever():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = _build_retriever()
    return _DEFAULT


def backend_name() -> str:
    """Which retriever is live — ``embed`` or ``tfidf`` (for the HUD / debug)."""
    return "embed" if isinstance(default_retriever(), EmbeddingRetriever) else "tfidf"


def retrieve(query: str, k: int = 4) -> list[dict]:
    """Top-k bylaw chunks for a query → [{doc_id, title, source, score}]."""
    return [
        {"doc_id": d.doc_id, "title": d.title, "source": d.source, "score": round(s, 4)}
        for d, s in default_retriever().query(query, k)
    ]
