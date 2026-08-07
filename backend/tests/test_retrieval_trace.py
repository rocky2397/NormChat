"""Tracing must not change retrieval.

RetrievalTrace exists so backend/eval/retrieval_probe.py can read the
per-stage rankings. The check for that refactor is a null result:
retrieve_sources() returns exactly the same sources whether or not a trace
is attached, and the trace's final stage corresponds 1:1 to what was
returned.
"""

import pytest

import services.llm as llm
from services.llm import RetrievalTrace, retrieve_sources

QUESTION = "Erläutere mir die Querkraftbemessung eines Stahlbetonbalkens"


def _meta(document_id, filename, page, reference):
    return {
        "document_id": document_id,
        "source_filename": filename,
        "page_number": page,
        "norm_reference": reference,
        "edition": "",
    }


# A miniature corpus with the shapes the pipeline distinguishes: EN body
# clauses, EN front matter, a national-annex chunk that carries no domain
# vocabulary and is only reachable through the clause lookup, and a
# same-clause-number chunk from another norm family.
CORPUS = {
    "en_62": (
        "6.2.3 Querkraft\nBauteile mit rechnerisch erforderlicher "
        "Querkraftbewehrung, Druckstrebenneigung und V_Rd,max.",
        _meta("en", "en.pdf", 97, "ÖNORM EN 1992-1-1"),
    ),
    "en_31": (
        "3.1.6 Bemessungswert der Betondruckfestigkeit\n(1)P Der "
        "Bemessungswert der Betondruckfestigkeit.",
        _meta("en", "en.pdf", 36, "ÖNORM EN 1992-1-1"),
    ),
    "en_front": (
        "Vorwort\nDieses Dokument wurde vom Technischen Komitee erstellt.",
        _meta("en", "en.pdf", 2, "ÖNORM EN 1992-1-1"),
    ),
    "b_92": (
        "9.2 Festlegung zu ÖNORM EN 1992-1-1, Abschnitt 6.2.3(2)\nDer "
        "empfohlene Wert wird übernommen.",
        _meta("b", "b.pdf", 21, "ÖNORM B 1992-1-1"),
    ),
    "snow": (
        "9.2.2 Außergewöhnliche Verhältnisse bei Schneeverwehungen.",
        _meta("b1991", "snow.pdf", 9, "ÖNORM B 1991-1-3"),
    ),
}

DENSE_ORDER = ["en_62", "en_31", "en_front", "snow", "b_92"]


class FakeCollection:
    def __init__(self):
        self._ids = list(CORPUS)

    def count(self):
        return len(self._ids)

    def query(self, query_embeddings, n_results, include):
        return {"ids": [DENSE_ORDER[:n_results]]}

    def get(self, include):
        return {
            "ids": self._ids,
            "documents": [CORPUS[cid][0] for cid in self._ids],
            "metadatas": [CORPUS[cid][1] for cid in self._ids],
        }


class FakeEmbeddings:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


@pytest.fixture()
def fake_pipeline(monkeypatch):
    monkeypatch.setattr(llm, "get_collection", lambda project_id: FakeCollection())
    monkeypatch.setattr(llm, "get_embeddings", lambda: FakeEmbeddings())
    # Deterministic stand-in for the cross-encoder: keep fused order. What
    # these tests assert is invariance between two identical calls, not
    # reranker quality.
    monkeypatch.setattr(
        llm, "rerank_ids", lambda question, ids, docs, top_k: list(ids)[:top_k]
    )
    # Small context so the annex chunk is not already in the first pass and
    # the clause lookup actually appends — the trace has to record both.
    monkeypatch.setattr(llm.settings, "top_k_chunks", 2)


class TestTraceIsANoOp:
    def test_sources_identical_with_and_without_trace(self, fake_pipeline):
        without = retrieve_sources("p1", QUESTION)
        traced = retrieve_sources("p1", QUESTION, trace=RetrievalTrace())
        assert without == traced
        assert len(without) > 0

    def test_repeated_traced_calls_are_stable(self, fake_pipeline):
        first = retrieve_sources("p1", QUESTION, trace=RetrievalTrace())
        second = retrieve_sources("p1", QUESTION, trace=RetrievalTrace())
        assert first == second


class TestTraceContents:
    def test_records_every_stage_in_pipeline_order(self, fake_pipeline):
        trace = RetrievalTrace()
        retrieve_sources("p1", QUESTION, trace=trace)
        assert trace.vector_ids == DENSE_ORDER
        assert sorted(trace.bm25_ids) == sorted(CORPUS)
        assert sorted(trace.fused_ids) == sorted(CORPUS)
        assert trace.reranked_ids == trace.fused_ids[:2]
        # The clause lookup runs after the rerank snapshot and extends it.
        assert trace.final_ids[: len(trace.reranked_ids)] == trace.reranked_ids

    def test_final_stage_matches_returned_sources_one_to_one(self, fake_pipeline):
        trace = RetrievalTrace()
        sources = retrieve_sources("p1", QUESTION, trace=trace)
        assert len(trace.final_ids) == len(sources)
        for cid, source in zip(trace.final_ids, sources):
            assert trace.id_to_meta[cid]["page_number"] == source.page_number
            assert CORPUS[cid][0] == source.chunk_text

    def test_clause_lookup_append_is_visible_as_reranked_vs_final(self, fake_pipeline):
        # b_92 has no vocabulary in common with the question; it can only
        # arrive through the clause lookup, i.e. after the reranked stage.
        trace = RetrievalTrace()
        retrieve_sources("p1", QUESTION, trace=trace)
        assert "b_92" not in trace.reranked_ids
        assert "b_92" in trace.final_ids

    def test_empty_collection_leaves_trace_empty(self, fake_pipeline, monkeypatch):
        class EmptyCollection(FakeCollection):
            def count(self):
                return 0

        monkeypatch.setattr(llm, "get_collection", lambda project_id: EmptyCollection())
        trace = RetrievalTrace()
        assert retrieve_sources("p1", QUESTION, trace=trace) == []
        assert trace.final_ids == []
