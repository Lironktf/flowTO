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
    hits = rag.retrieve("temporary traffic regulation approved event plan contraflow", k=2)
    ids = [h["doc_id"] for h in hits]
    assert "ch950_traffic" in ids
