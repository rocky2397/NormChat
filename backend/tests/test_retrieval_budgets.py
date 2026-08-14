"""The two second-pass mechanisms must not spend each other's budget, and
the clause lookup must not spend its own on one page twice.

_admit_annex_deltas() and the clause lookup both append to final_ids, and
the lookup's cap used to be read off len(final_ids) as top_k + 3. So a full
delta admission consumed the lookup's allowance before it started and left
it a single slot — silently, and worst on the annex-heavy questions both
mechanisms exist to serve.

Restoring that budget then exposed what the lookup spends it on: on Q5 all
three slots went to fragments of one continued table on the same page
(eval/runs/2026-08-13-budget-separation-and-index-cache.md).
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

# Four parents, so the clause lookup has enough distinct targets to fill
# its budget — otherwise the fixture, not the budget, sets the ceiling.
TOP_K = 4

EN = "ÖNORM EN 1992-1-1"
B = "ÖNORM B 1992-1-1"
# Same family (1992), a different document — the clause lookup is scoped to
# the family, so a lookup target has to live inside it.
C = "ÖNORM B 1992-3"


def _meta(document_id, reference, page, raw_text=None):
    meta = {
        "document_id": document_id,
        "source_filename": f"{document_id}.pdf",
        "page_number": page,
        "norm_reference": reference,
        "edition": "",
    }
    if raw_text is not None:
        meta["raw_text"] = raw_text
    return meta


def _delta(own_clause: str, parent_clause: str) -> str:
    return (
        f"{own_clause} Festlegung zu ÖNORM EN 1992-1-1:2015, "
        f"Abschnitt {parent_clause}\nDer empfohlene Wert wird übernommen."
    )


def _rule(own_clause: str, parent_clause: str) -> str:
    return f"{own_clause} Ergänzende Regel zu Abschnitt {parent_clause} für Fertigteile."


# Three parent clauses, each with a delta that admission will re-admit and a
# separate chunk in a third document that only the clause lookup can reach.
# The lookup targets carry no raw_text, so delta admission ignores them and
# the two mechanisms stay distinguishable. Every chunk sits on its own page,
# so page-level deduplication is not what is under test here.
CORPUS = {
    "en_316": ("3.1.6 Bemessungswert der Betondruckfestigkeit\n(1)P ...", _meta("en", EN, 36)),
    "en_623": ("6.2.3 Querkraft\nBauteile mit Querkraftbewehrung ...", _meta("en", EN, 97)),
    "en_952": ("9.5.2 Stützen\nLängsbewehrung ...", _meta("en", EN, 120)),
    "en_742": ("7.4.2 Begrenzung der Verformungen\nGrenzwerte ...", _meta("en", EN, 130)),
    "b_316": (_delta("6.1.4", "3.1.6(1)P"), _meta("b", B, 12, _delta("6.1.4", "3.1.6(1)P"))),
    "b_623": (_delta("9.2.1", "6.2.3(2)"), _meta("b", B, 21, _delta("9.2.1", "6.2.3(2)"))),
    "b_952": (_delta("9.5.1", "9.5.2(2)"), _meta("b", B, 28, _delta("9.5.1", "9.5.2(2)"))),
    "c_316": (_rule("5.1", "3.1.6"), _meta("c", C, 5)),
    "c_623": (_rule("5.2", "6.2.3"), _meta("c", C, 6)),
    "c_952": (_rule("5.3", "9.5.2"), _meta("c", C, 7)),
    "c_742": (_rule("5.4", "7.4.2"), _meta("c", C, 8)),
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


def _install(monkeypatch, corpus=None, top_k=TOP_K, keep="en_"):
    monkeypatch.setattr(llm, "get_collection", lambda project_id: FakeCollection(corpus))
    monkeypatch.setattr(llm, "get_embeddings", lambda: FakeEmbeddings())
    # The reranker keeps the European parent clauses and nothing else, which
    # is the situation both mechanisms are built for: the parents are found,
    # the Austrian deviations are not.
    monkeypatch.setattr(
        llm,
        "rerank_ids",
        lambda question, ids, docs, top_k_: [c for c in ids if c.startswith(keep)][:top_k_],
    )
    monkeypatch.setattr(llm.settings, "top_k_chunks", top_k)


@pytest.fixture()
def fake_pipeline(monkeypatch):
    _install(monkeypatch)


def _trace():
    trace = RetrievalTrace()
    retrieve_sources("p1", QUESTION, trace=trace)
    return trace


class TestBudgetsAreIndependent:
    def test_delta_admission_fills_its_own_budget(self, fake_pipeline):
        trace = _trace()
        assert len(trace.deltas_admitted_ids) == TOP_K + ANNEX_DELTA_ADMIT_LIMIT
        assert {"b_316", "b_623", "b_952"} <= set(trace.deltas_admitted_ids)
        # And the reranker's own column reports the reranker only.
        assert len(trace.reranked_ids) == TOP_K
        assert not {"b_316", "b_623", "b_952"} & set(trace.reranked_ids)

    def test_clause_lookup_keeps_its_budget_after_a_full_admission(self, fake_pipeline):
        # The regression: with the cap read off len(final_ids), this was 1.
        trace = _trace()
        assert len(trace.final_ids) - len(trace.deltas_admitted_ids) == CLAUSE_LOOKUP_LIMIT

    def test_the_lookup_reaches_all_three_target_documents(self, fake_pipeline):
        # The user-visible half: three national modifications in context
        # instead of one, on a question about exactly those.
        assert {"c_316", "c_623", "c_952"} <= set(_trace().final_ids)

    def test_lookup_is_still_capped_when_nothing_was_admitted(self, monkeypatch):
        # Removing raw_text makes every delta invisible to admission, so the
        # lookup runs alone — and must still stop at its own limit rather
        # than inheriting the slack.
        unenriched = {
            cid: (text, {k: v for k, v in meta.items() if k != "raw_text"})
            for cid, (text, meta) in CORPUS.items()
        }
        _install(monkeypatch, unenriched)
        trace = _trace()
        assert len(trace.reranked_ids) == TOP_K
        assert trace.deltas_admitted_ids == trace.reranked_ids
        assert len(trace.final_ids) - len(trace.deltas_admitted_ids) == CLAUSE_LOOKUP_LIMIT

    def test_sources_returned_match_the_final_stage(self, fake_pipeline):
        trace = RetrievalTrace()
        sources = retrieve_sources("p1", QUESTION, trace=trace)
        expected = TOP_K + ANNEX_DELTA_ADMIT_LIMIT + CLAUSE_LOOKUP_LIMIT
        assert len(sources) == len(trace.final_ids) == expected


# Two parent clauses whose modifications live in one document; only the page
# they sit on differs between the two corpora below.
def _two_clause_corpus(second_page: int) -> dict:
    return {
        "en_316": ("3.1.6 Bemessungswert der Betondruckfestigkeit ...", _meta("en", EN, 36)),
        "en_623": ("6.2.3 Querkraft ...", _meta("en", EN, 97)),
        "d_316": (_rule("5.1", "3.1.6"), _meta("d", C, 5)),
        "d_623": (_rule("5.2", "6.2.3"), _meta("d", C, second_page)),
    }


class TestPageLevelDeduplication:
    def test_two_clauses_resolving_to_one_page_yield_one_chunk(self, monkeypatch):
        # A citation is a page: both chunks open the same source card on the
        # same highlight, so the second spends a slot for nothing.
        _install(monkeypatch, _two_clause_corpus(second_page=5), top_k=2)
        trace = _trace()
        appended = [c for c in trace.final_ids if c not in trace.deltas_admitted_ids]
        assert appended == ["d_316"]

    def test_the_same_clauses_on_different_pages_still_yield_two(self, monkeypatch):
        # The control: deduplication must key on the page, not on the
        # document, or it would suppress genuine second modifications.
        _install(monkeypatch, _two_clause_corpus(second_page=6), top_k=2)
        trace = _trace()
        appended = [c for c in trace.final_ids if c not in trace.deltas_admitted_ids]
        assert appended == ["d_316", "d_623"]

    def test_a_page_already_in_context_is_not_looked_up_again(self, monkeypatch):
        # Seeded from final_ids, so a page delta admission already placed is
        # covered too — that is Q5's B 1992-1-1 p. 12 appearing twice.
        corpus = _two_clause_corpus(second_page=6)
        corpus["d_316"] = (corpus["d_316"][0], _meta("en", EN, 97))
        _install(monkeypatch, corpus, top_k=2)
        trace = _trace()
        appended = [c for c in trace.final_ids if c not in trace.deltas_admitted_ids]
        assert "d_316" not in appended


MODIFICATION = (
    "9.2.4 Festlegung zur ÖNORM EN 1992-1-1:2015, Abschnitt 6.2.3(2)\n"
    "Bei einer Spannungsbegrenzung gilt ..."
)


class TestPageRuleYieldsToTheRightClause:
    """Two distinct clauses can share a page.

    ÖNORM B 1992-1-1 p. 21 carries §9.1.1, a bending Ergänzung, and §9.2.4,
    the Querkraft Festlegung. Parent clause 6.1 is walked before 6.2.3, so a
    blanket page rule let the bending clause take the page and locked out the
    shear clause — on the question whose whole purpose is to surface it.
    """

    def _corpus(self):
        return {
            "en_61": ("6.1 Biegung mit Normalkraft ...", _meta("en", EN, 90)),
            "en_623": ("6.2.3 Querkraft — Fachwerkmodell ...", _meta("en", EN, 97)),
            # Both national clauses live on page 21 of the same document.
            "b_911": (
                "9.1.1 Ergänzung zur ÖNORM EN 1992-1-1:2015, Abschnitt 6.1\nBei ...",
                _meta("b", B, 21),
            ),
            "b_924": (MODIFICATION, _meta("b", B, 21)),
        }

    def test_the_second_clause_on_a_taken_page_is_still_admitted(self, monkeypatch):
        _install(monkeypatch, self._corpus(), top_k=2)
        trace = _trace()
        appended = [c for c in trace.final_ids if c not in trace.deltas_admitted_ids]
        assert appended == ["b_911", "b_924"]

    def test_a_candidate_stating_no_modification_is_still_deduplicated(self, monkeypatch):
        # The register case the page rule exists for: same page, no
        # Festlegung, so the second one is still dropped.
        corpus = self._corpus()
        corpus["b_924"] = ("Tabelle 1 | 6.2.3 | 6.1 | 7.2 |", _meta("b", B, 21))
        _install(monkeypatch, corpus, top_k=2)
        trace = _trace()
        appended = [c for c in trace.final_ids if c not in trace.deltas_admitted_ids]
        assert appended == ["b_911"]
