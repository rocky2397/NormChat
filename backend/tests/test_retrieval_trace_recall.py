"""Recall computation, rendering, and a full run_question_trace() pass.

run_question_trace() calls the whole chat() pipeline once — retrieval,
answer generation and excerpt grounding — so this is the check that a
question's expected sources come out with the right per-stage rank *and*
the right grounding status, not just that retrieval alone behaves (that is
eval/retrieval_probe.py's job).
"""

import pytest

import services.llm as llm
import services.retrieval_trace as retrieval_trace
from services.retrieval_trace import (
    ContextSourceTrace,
    ExpectedSource,
    ExpectedSourceTrace,
    QuestionSpec,
    recall_at,
    render_question_trace,
    run_question_trace,
    unused_context_rate,
)


def _meta(document_id, filename, page, reference):
    return {
        "document_id": document_id,
        "source_filename": filename,
        "page_number": page,
        "norm_reference": reference,
        "edition": "",
    }


# Mirrors the corpus shape in test_retrieval_trace.py: an EN clause the
# dense/lexical rankings reach directly, and a national-annex clause only
# reachable through the clause lookup once top_k_chunks is small.
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
    "b_92": (
        "9.2 Festlegung zu ÖNORM EN 1992-1-1, Abschnitt 6.2.3(2)\nDer "
        "empfohlene Wert wird übernommen.",
        _meta("b", "b.pdf", 21, "ÖNORM B 1992-1-1"),
    ),
    # Shares no vocabulary with the question and cites no clause the other
    # chunks reference, so it should never rank into the top_k_chunks=2
    # reranked set nor be pulled in by the clause lookup — the case a
    # resolved-but-unreached expected source needs to exercise.
    "en_99": (
        "8.4 Verankerung von Betonstahl\nAllgemeines zur Verankerung und "
        "zum Verbund.",
        _meta("en", "en.pdf", 150, "ÖNORM EN 1992-1-1"),
    ),
}

DENSE_ORDER = ["en_62", "en_31", "b_92", "en_99"]


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
    collection = FakeCollection()
    monkeypatch.setattr(llm, "get_collection", lambda project_id: collection)
    monkeypatch.setattr(llm, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(retrieval_trace, "get_collection", lambda project_id: collection)
    # Deterministic stand-in for the cross-encoder, as in test_retrieval_trace.py.
    monkeypatch.setattr(
        llm, "rerank_ids", lambda question, ids, docs, top_k: list(ids)[:top_k]
    )
    # Small context so the annex chunk (b_92) is not already in the first
    # pass and the clause lookup actually appends it.
    monkeypatch.setattr(llm.settings, "top_k_chunks", 2)
    # No OpenAI calls in a unit test: a canned answer, and a grounding
    # excerpt for exactly one of the two final sources so the test can tell
    # the grounded source from the ungrounded one.
    monkeypatch.setattr(llm, "generate_answer", lambda question, sources: "Antwort.")
    monkeypatch.setattr(
        llm,
        "extract_citation_excerpts",
        lambda question, answer, sources: {1: "Bauteile mit rechnerisch erforderlicher"},
    )


QUESTION_SPEC = QuestionSpec(
    number=3,
    text="Erläutere mir die Querkraftbemessung eines Stahlbetonbalkens",
    expected=(
        ExpectedSource("ÖNORM EN 1992-1-1", 97, "6.2.3"),
        ExpectedSource("ÖNORM B 1992-1-1", 21, "9.2"),
    ),
)


class TestRunQuestionTrace:
    def test_stage_ranks_localize_dense_vs_clause_lookup(self, fake_pipeline):
        trace = run_question_trace("p1", QUESTION_SPEC)
        en = next(t for t in trace.expected if t.expected.norm_reference == "ÖNORM EN 1992-1-1")
        b = next(t for t in trace.expected if t.expected.norm_reference == "ÖNORM B 1992-1-1")
        assert en.stage_ranks["dense"] == 1
        assert en.stage_ranks["final"] == 1
        # b_92 has no vocabulary in common with the question; it only
        # arrives through the clause lookup, so "reranked" is a miss and
        # "final" is not.
        assert b.stage_ranks["reranked"] is None
        assert b.stage_ranks["final"] is not None

    def test_grounded_reflects_the_actual_highlight_snippet(self, fake_pipeline):
        trace = run_question_trace("p1", QUESTION_SPEC)
        en = next(t for t in trace.expected if t.expected.norm_reference == "ÖNORM EN 1992-1-1")
        b = next(t for t in trace.expected if t.expected.norm_reference == "ÖNORM B 1992-1-1")
        # The excerpt was grounded against source index 1, which is en_62.
        assert en.grounded is True
        assert b.grounded is False

    def test_context_traces_cover_every_final_source(self, fake_pipeline):
        trace = run_question_trace("p1", QUESTION_SPEC)
        # en_62 and en_31 are selected directly, b_92 arrives via the clause
        # lookup; en_99 never appears anywhere in the final context.
        assert len(trace.context) == 3
        assert sum(1 for c in trace.context if c.grounded) == 1

    def test_a_source_never_reached_reports_not_reached(self, fake_pipeline):
        spec = QuestionSpec(
            number=99,
            text=QUESTION_SPEC.text,
            expected=(ExpectedSource("ÖNORM EN 1992-1-1", 150, "8.4"),),
        )
        trace = run_question_trace("p1", spec)
        (only,) = trace.expected
        # en_99 exists in the corpus (so resolution succeeds) but never
        # ranks inside top_k_chunks=2 or the clause lookup for this question.
        assert only.stage_ranks["final"] is None
        assert only.grounded is None


class TestRecallAt:
    def _trace(self, ranks):
        return ExpectedSourceTrace(
            expected=ExpectedSource("X", 1, None),
            chunk_ids=("x",),
            stage_ranks=ranks,
            grounded=None,
        )

    def test_counts_hits_at_or_above_the_cutoff(self):
        traces = [self._trace({"final": 4}), self._trace({"final": None})]
        assert recall_at(traces, "final", 10) == (1, 2)
        assert recall_at(traces, "final", 3) == (0, 2)


class TestUnusedContextRate:
    def test_counts_ungrounded_context_sources(self):
        context = [
            ContextSourceTrace("A", 1, grounded=True),
            ContextSourceTrace("B", 2, grounded=False),
            ContextSourceTrace("C", 3, grounded=False),
        ]
        assert unused_context_rate(context) == (2, 3)

    def test_empty_context_is_zero_of_zero(self):
        assert unused_context_rate([]) == (0, 0)


class TestRenderQuestionTrace:
    def test_report_includes_ranks_recall_and_grounding(self, fake_pipeline):
        trace = run_question_trace("p1", QUESTION_SPEC)
        report = render_question_trace(trace, date_str="2026-08-26")
        assert "# Retrieval trace — Q3 — 2026-08-26" in report
        assert "`ÖNORM EN 1992-1-1`" in report
        assert "`ÖNORM B 1992-1-1`" in report
        assert "Unused-context rate: 2/3 (0.67)" in report
