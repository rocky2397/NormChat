"""The two second-pass mechanisms must not spend each other's budget.

_admit_annex_deltas() and the clause lookup both append to final_ids, and
the lookup's cap used to be read off len(final_ids) as top_k + 3. So a full
delta admission consumed the lookup's allowance before it started and left
it a single slot — silently, and worst on the annex-heavy questions both
mechanisms exist to serve.
"""

import pytest

import services.llm as llm
from services.llm import (
    ANNEX_DELTA_ADMIT_LIMIT,
    CLAUSE_LOOKUP_LIMIT,
    RetrievalTrace,
    retrieve_sources,
)

QUESTION = "Welche Festlegungen gelten für Stahlbeton nach ÖNORM B 1992-1-1?"

TOP_K = 3


def _meta(document_id, reference, raw_text=None):
    meta = {
        "document_id": document_id,
        "source_filename": f"{document_id}.pdf",
        "page_number": 10,
        "norm_reference": reference,
        "edition": "",
    }
    if raw_text is not None:
        meta["raw_text"] = raw_text
    return meta


EN = "ÖNORM EN 1992-1-1"
B = "ÖNORM B 1992-1-1"
# Same family (1992), a different document — the clause lookup is scoped to
# the family, so a lookup target has to live inside it.
C = "ÖNORM B 1992-3"


def _delta(own_clause: str, parent_clause: str) -> str:
    return (
        f"{own_clause} Festlegung zu ÖNORM EN 1992-1-1:2015, "
        f"Abschnitt {parent_clause}\nDer empfohlene Wert wird übernommen."
    )


# Three parent clauses, each with a delta that admission will re-admit and a
# separate chunk in a third document that only the clause lookup can reach.
# The lookup targets carry no raw_text, so delta admission ignores them and
# the two mechanisms stay distinguishable.
CORPUS = {
    "en_316": ("3.1.6 Bemessungswert der Betondruckfestigkeit\n(1)P ...", _meta("en", EN)),
    "en_623": ("6.2.3 Querkraft\nBauteile mit Querkraftbewehrung ...", _meta("en", EN)),
    "en_952": ("9.5.2 Stützen\nLängsbewehrung und Mindestdurchmesser ...", _meta("en", EN)),
    "b_316": (_delta("6.1.4", "3.1.6(1)P"), _meta("b", B, _delta("6.1.4", "3.1.6(1)P"))),
    "b_623": (_delta("9.2.1", "6.2.3(2)"), _meta("b", B, _delta("9.2.1", "6.2.3(2)"))),
    "b_952": (_delta("9.5.1", "9.5.2(2)"), _meta("b", B, _delta("9.5.1", "9.5.2(2)"))),
    "c_316": ("5.1 Ergänzende Regel zu Abschnitt 3.1.6 für Fertigteile.", _meta("c", C)),
    "c_623": ("5.2 Ergänzende Regel zu Abschnitt 6.2.3 für Fertigteile.", _meta("c", C)),
    "c_952": ("5.3 Ergänzende Regel zu Abschnitt 9.5.2 für Fertigteile.", _meta("c", C)),
}


class FakeCollection:
    def __init__(self, corpus=None):
        self._corpus = corpus if corpus is not None else CORPUS
        self._ids = list(self._corpus)

    def count(self):
        return len(self._ids)

    def query(self, query_embeddings, n_results, include):
        return {"ids": [self._ids[:n_results]]}

    def get(self, include):
        return {
            "ids": self._ids,
            "documents": [self._corpus[cid][0] for cid in self._ids],
            "metadatas": [self._corpus[cid][1] for cid in self._ids],
        }


class FakeEmbeddings:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


@pytest.fixture()
def fake_pipeline(monkeypatch):
    monkeypatch.setattr(llm, "get_collection", lambda project_id: FakeCollection())
    monkeypatch.setattr(llm, "get_embeddings", lambda: FakeEmbeddings())
    # The reranker keeps the European parent clauses and nothing else, which
    # is the situation both mechanisms are built for: the parents are found,
    # the Austrian deviations are not.
    monkeypatch.setattr(
        llm,
        "rerank_ids",
        lambda question, ids, docs, top_k: [c for c in ids if c.startswith("en_")][:top_k],
    )
    monkeypatch.setattr(llm.settings, "top_k_chunks", TOP_K)


def _trace(project="p1"):
    trace = RetrievalTrace()
    retrieve_sources(project, QUESTION, trace=trace)
    return trace


class TestBudgetsAreIndependent:
    def test_delta_admission_fills_its_own_budget(self, fake_pipeline):
        trace = _trace()
        assert len(trace.reranked_ids) == TOP_K + ANNEX_DELTA_ADMIT_LIMIT
        assert {"b_316", "b_623", "b_952"} <= set(trace.reranked_ids)

    def test_clause_lookup_keeps_its_budget_after_a_full_admission(self, fake_pipeline):
        # The regression: with the cap read off len(final_ids), this was 1.
        trace = _trace()
        appended = len(trace.final_ids) - len(trace.reranked_ids)
        assert appended == CLAUSE_LOOKUP_LIMIT

    def test_the_lookup_reaches_all_three_target_documents(self, fake_pipeline):
        # The user-visible half: three national modifications in context
        # instead of one, on a question about exactly those.
        assert {"c_316", "c_623", "c_952"} <= set(_trace().final_ids)

    def test_lookup_is_still_capped_when_nothing_was_admitted(
        self, fake_pipeline, monkeypatch
    ):
        # Removing raw_text makes every delta invisible to admission, so the
        # lookup runs alone — and must still stop at its own limit rather
        # than inheriting the slack.
        unenriched = {
            cid: (text, {k: v for k, v in meta.items() if k != "raw_text"})
            for cid, (text, meta) in CORPUS.items()
        }
        monkeypatch.setattr(
            llm, "get_collection", lambda project_id: FakeCollection(unenriched)
        )
        trace = _trace()
        assert len(trace.reranked_ids) == TOP_K
        assert len(trace.final_ids) - len(trace.reranked_ids) == CLAUSE_LOOKUP_LIMIT

    def test_sources_returned_match_the_final_stage(self, fake_pipeline):
        trace = RetrievalTrace()
        sources = retrieve_sources("p1", QUESTION, trace=trace)
        assert len(sources) == len(trace.final_ids) == TOP_K + ANNEX_DELTA_ADMIT_LIMIT + (
            CLAUSE_LOOKUP_LIMIT
        )
