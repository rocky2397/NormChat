"""The corpus is read once per version of a collection, not once per query.

Reading it costs ~300 MB on the 137-document DIN corpus — ~100 MB of chunk
text plus ~200 MB of metadata, which carries raw_text and so holds every chunk
a second time. Allocating and freeing that per question made resident memory
ratchet upward until the instance was killed ("Ran out of memory (used over
2GB)") at roughly the seventh question, even though logical usage was flat:
large freed blocks are not handed back to the OS.

What has to stay true is that a *changed* collection is never served from the
slot — enrichment in particular, which rewrites chunk text in place and leaves
both the id set and the count untouched.
"""

import pytest

import services.llm as llm
from services.llm import retrieve_sources
from services.storage import bump_collection_version

QUESTION = "Welche Festlegungen gelten für Stahlbeton?"

CORPUS = {
    "en_1": ("6.2.3 Querkraft und Querkraftbewehrung", {"document_id": "en", "page_number": 97,
             "norm_reference": "DIN EN 1992-1-1", "edition": "", "source_filename": "en.pdf"}),
    "en_2": ("3.1.6 Bemessungswert der Betondruckfestigkeit", {"document_id": "en", "page_number": 36,
             "norm_reference": "DIN EN 1992-1-1", "edition": "", "source_filename": "en.pdf"}),
}


class CountingCollection:
    """Counts full-corpus reads, which is the cost under test."""

    def __init__(self, corpus):
        self._corpus = dict(corpus)
        self.reads = 0

    def count(self):
        return len(self._corpus)

    def query(self, query_embeddings, n_results, include):
        return {"ids": [list(self._corpus)[:n_results]]}

    def get(self, include):
        self.reads += 1
        ids = list(self._corpus)
        return {
            "ids": ids,
            "documents": [self._corpus[c][0] for c in ids],
            "metadatas": [self._corpus[c][1] for c in ids],
        }

    def enrich_in_place(self, chunk_id, text):
        """What reference enrichment does: same id, same count, new text."""
        meta = self._corpus[chunk_id][1]
        self._corpus[chunk_id] = (text, meta)


class FakeEmbeddings:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


@pytest.fixture()
def collection(monkeypatch):
    live = CountingCollection(CORPUS)
    monkeypatch.setattr(llm, "get_collection", lambda project_id: live)
    monkeypatch.setattr(llm, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(llm, "rerank_ids", lambda q, ids, docs, k: list(ids)[:k])
    return live


def test_repeated_questions_read_the_corpus_once(collection):
    for _ in range(5):
        retrieve_sources("project-a", QUESTION)

    assert collection.reads == 1


def test_a_write_makes_the_next_question_re_read(collection):
    retrieve_sources("project-a", QUESTION)
    assert collection.reads == 1

    bump_collection_version("project-a")
    retrieve_sources("project-a", QUESTION)

    assert collection.reads == 2


def test_enrichment_in_place_is_not_served_from_the_slot(collection):
    """The case a count or an id set cannot catch: enrichment rewrites a
    chunk's indexed text and changes neither."""
    retrieve_sources("project-a", QUESTION)
    before = collection.count()

    collection.enrich_in_place("en_1", "6.2.3 Querkraft — NDP Zu 6.2.3(2)")
    bump_collection_version("project-a")
    sources = retrieve_sources("project-a", QUESTION)

    assert collection.count() == before
    assert collection.reads == 2
    assert any("NDP Zu 6.2.3(2)" in source.chunk_text for source in sources)


def test_another_project_is_never_served_the_cached_corpus(monkeypatch):
    a = CountingCollection(CORPUS)
    b = CountingCollection({"other_1": ("NA 1 Anwendungsbereich", {
        "document_id": "b", "page_number": 3, "norm_reference": "DIN EN 1992-1-1/NA",
        "edition": "", "source_filename": "b.pdf"})})
    live = {"project-a": a, "project-b": b}
    monkeypatch.setattr(llm, "get_collection", lambda project_id: live[project_id])
    monkeypatch.setattr(llm, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(llm, "rerank_ids", lambda q, ids, docs, k: list(ids)[:k])

    retrieve_sources("project-a", QUESTION)
    sources = retrieve_sources("project-b", QUESTION)

    assert a.reads == 1 and b.reads == 1
    assert [s.norm_reference for s in sources] == ["DIN EN 1992-1-1/NA"]
