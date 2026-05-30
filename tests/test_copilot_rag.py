"""P09 — RAG over the bylaw corpus retrieves the relevant doc."""

from __future__ import annotations

from torontosim.copilot import rag


def test_corpus_loads():
    docs = rag.load_corpus()
    assert len(docs) >= 5
    assert any("880" in d.title for d in docs)


def test_fire_route_query_retrieves_ch880():
    hits = rag.retrieve("emergency fire route access closure", k=3)
    ids = [h["doc_id"] for h in hits]
    assert "ch880_fire_route" in ids
    # Top hit should be the fire-route doc.
    assert hits[0]["doc_id"] == "ch880_fire_route"


def test_transit_query_retrieves_streetcar_docs():
    hits = rag.retrieve("streetcar replacement bus lane 509 511", k=3)
    ids = [h["doc_id"] for h in hits]
    assert "ttc_replacement" in ids


def test_event_tmp_query_retrieves_ch950():
    hits = rag.retrieve("temporary traffic regulation approved event plan contraflow", k=4)
    ids = [h["doc_id"] for h in hits]
    assert "ch950_traffic" in ids


def test_expanded_corpus_has_real_municipal_code_sections():
    docs = rag.load_corpus()
    # The bake added real § sections alongside the curated summaries.
    assert any(d.doc_id.startswith("mc950_") for d in docs)
    assert any("legdocs/municode" in d.source for d in docs)


def test_backend_name_reports_active_retriever():
    assert rag.backend_name() in ("embed", "tfidf")


def test_embedding_retriever_parity_when_available():
    """If the ai extra is installed, the embed retriever finds the fire-route doc."""
    import pytest

    try:
        r = rag.EmbeddingRetriever(rag.load_corpus())
    except Exception:
        pytest.skip("sentence-transformers not installed (TF-IDF is the local default)")
    ids = [d.doc_id for d, _ in r.query("emergency fire route access closure", k=5)]
    assert any("880" in i for i in ids)
