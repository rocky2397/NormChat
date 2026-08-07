"""Pre-retrieval sub-query expansion (Q2 charring gap).

The probes widen retrieval and do nothing else: they are fused into the
candidate ranking, never shown, never stored, and never allowed into the
answering context. On any failure expansion degrades silently to today's
single-query retrieval.
"""

import logging

import services.llm as llm_module
import services.query_expansion as query_expansion
from config import settings
from models.chat import SourceChunk
from services.llm import _format_context, retrieve_sources
from services.query_expansion import expand_query


def _fake_chat(queries=None, error=None):
    """A ChatOpenAI stand-in returning canned sub-queries or raising."""

    class FakeStructured:
        def invoke(self, prompt):
            if error is not None:
                raise error
            return query_expansion._SubQueries(queries=queries)

    class FakeChat:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, schema):
            return FakeStructured()

    return FakeChat


class TestExpandQuery:
    def test_flag_defaults_to_off(self):
        assert settings.query_expansion_enabled is False

    def test_disabled_flag_makes_no_llm_call(self, monkeypatch):
        def explode(**kwargs):
            raise AssertionError("expansion must not call the model when disabled")

        monkeypatch.setattr(query_expansion, "ChatOpenAI", explode)
        assert expand_query("Wie bemesse ich einen Holzbalken für R60?") == []

    def test_without_api_key_returns_no_queries(self, monkeypatch):
        monkeypatch.setattr(settings, "query_expansion_enabled", True)
        monkeypatch.setattr(settings, "openai_api_key", "")
        assert expand_query("Frage") == []

    def test_returns_cleaned_and_capped_sub_queries(self, monkeypatch):
        monkeypatch.setattr(settings, "query_expansion_enabled", True)
        monkeypatch.setattr(settings, "openai_api_key", "test-key")
        question = "Wie weise ich R60 nach?"
        raw = [
            "  Abbrandtiefe Bemessungswert  ",
            "",
            "Wie weise ich R60 nach?",  # echo of the question adds nothing
            "ideeller Restquerschnitt",
            "Abbrandtiefe Bemessungswert",  # duplicate
            "Feuerwiderstandsdauer Bemessungswert",
            "Brandschutzbekleidung",
            "eine Anfrage zu viel",
        ]
        monkeypatch.setattr(query_expansion, "ChatOpenAI", _fake_chat(queries=raw))

        result = expand_query(question)

        assert result[:2] == ["Abbrandtiefe Bemessungswert", "ideeller Restquerschnitt"]
        assert question not in result
        assert len(result) == settings.query_expansion_max_queries

    def test_model_failure_returns_no_queries(self, monkeypatch):
        monkeypatch.setattr(settings, "query_expansion_enabled", True)
        monkeypatch.setattr(settings, "openai_api_key", "test-key")
        monkeypatch.setattr(
            query_expansion, "ChatOpenAI", _fake_chat(error=TimeoutError("slow"))
        )
        assert expand_query("Frage") == []

    def test_sub_queries_are_logged_for_run_notes(self, monkeypatch, caplog):
        monkeypatch.setattr(settings, "query_expansion_enabled", True)
        monkeypatch.setattr(settings, "openai_api_key", "test-key")
        monkeypatch.setattr(
            query_expansion, "ChatOpenAI", _fake_chat(queries=["Abbrandtiefe"])
        )
        with caplog.at_level(logging.INFO, logger="services.query_expansion"):
            expand_query("Wie weise ich R60 nach?")
        assert "Abbrandtiefe" in caplog.text


# A miniature corpus around the Q2 shape: the charring chunk shares not a
# single token with the question, so only an expansion probe can reach it.
QUESTION = "Wie weise ich den Feuerwiderstand R60 für einen Holzbalken nach?"
CORPUS = [
    ("general", "Feuerwiderstand R60 Holzbalken Anforderungen an tragende Bauteile"),
    ("load", "Feuerwiderstand von Bauteilen: Einwirkungen im Brandfall"),
    ("char", "Abbrandtiefe und ideeller Restquerschnitt in der Brandbemessung von Holz"),
    ("snow", "Schneelasten auf Dächern der Alpenregion"),
]
PROBES = ["Abbrandtiefe Brandbemessung", "ideeller Restquerschnitt"]


def _tokens(text):
    import re

    return set(re.findall(r"\w+", text.lower()))


def _overlap_ranking(query, ids, documents):
    """Rank by shared-token count, matches only — a stand-in for both the
    dense search and BM25, deterministic and inspectable."""
    scored = [
        (len(_tokens(query) & _tokens(doc)), i)
        for i, doc in enumerate(documents)
    ]
    return [ids[i] for score, i in sorted(scored, key=lambda s: (-s[0], s[1])) if score > 0]


class _FakeEmbeddings:
    def embed_query(self, text):
        # The "vector" is the query text itself; only _FakeCollection reads it.
        return text


class _FakeCollection:
    def __init__(self, corpus):
        self._ids = [cid for cid, _ in corpus]
        self._docs = [doc for _, doc in corpus]

    def count(self):
        return len(self._ids)

    def get(self, include):
        metadatas = [
            {
                "document_id": f"doc-{cid}",
                "source_filename": f"{cid}.pdf",
                "page_number": 1,
                "norm_reference": "",
                "edition": "",
            }
            for cid in self._ids
        ]
        return {"ids": list(self._ids), "documents": list(self._docs), "metadatas": metadatas}

    def query(self, query_embeddings, n_results, include):
        [query] = query_embeddings
        return {"ids": [_overlap_ranking(query, self._ids, self._docs)[:n_results]]}


def _patch_retrieval(monkeypatch, sub_queries):
    monkeypatch.setattr(settings, "top_k_chunks", 2)
    monkeypatch.setattr(llm_module, "get_collection", lambda project_id: _FakeCollection(CORPUS))
    monkeypatch.setattr(llm_module, "get_embeddings", lambda: _FakeEmbeddings())
    monkeypatch.setattr(llm_module, "bm25_rank_ids", _overlap_ranking)
    # The cross-encoder would download a real model; ranking is under the
    # fusion's control here, so passing the fused order through is enough.
    monkeypatch.setattr(llm_module, "rerank_ids", lambda q, ids, docs, top_k: ids[:top_k])
    if sub_queries is not None:
        monkeypatch.setattr(llm_module, "expand_query", lambda question: sub_queries)


def _texts(sources):
    return [source.chunk_text for source in sources]


class TestRetrieveSourcesFusion:
    def test_without_expansion_the_charring_chunk_is_unreachable(self, monkeypatch):
        _patch_retrieval(monkeypatch, sub_queries=[])
        texts = _texts(retrieve_sources("p1", QUESTION))
        assert texts == [CORPUS[0][1], CORPUS[1][1]]

    def test_probe_rankings_are_fused_and_reach_the_charring_chunk(self, monkeypatch):
        _patch_retrieval(monkeypatch, sub_queries=PROBES)
        texts = _texts(retrieve_sources("p1", QUESTION))
        assert CORPUS[2][1] in texts  # the chunk no question token can reach
        assert CORPUS[0][1] in texts  # the question's own best hit survives

    def test_expansion_failure_falls_back_to_single_query_retrieval(self, monkeypatch):
        # The real expand_query runs, its model call fails — retrieval must
        # succeed with exactly the unexpanded result.
        _patch_retrieval(monkeypatch, sub_queries=None)
        monkeypatch.setattr(settings, "query_expansion_enabled", True)
        monkeypatch.setattr(settings, "openai_api_key", "test-key")
        monkeypatch.setattr(
            query_expansion, "ChatOpenAI", _fake_chat(error=RuntimeError("api down"))
        )
        texts = _texts(retrieve_sources("p1", QUESTION))
        assert texts == [CORPUS[0][1], CORPUS[1][1]]


class TestProbesNeverReachTheAnswer:
    def test_generated_text_stays_out_of_sources_and_context(self, monkeypatch):
        sentinel = "PROBENVOKABULAR Abbrandtiefe Restquerschnitt"
        _patch_retrieval(monkeypatch, sub_queries=[sentinel])

        sources = retrieve_sources("p1", QUESTION)

        corpus_texts = {doc for _, doc in CORPUS}
        # Every source card is a verbatim stored chunk — nothing generated.
        assert all(source.chunk_text in corpus_texts for source in sources)
        assert all("PROBENVOKABULAR" not in source.chunk_text for source in sources)
        # The answering context is built from those same sources only.
        assert "PROBENVOKABULAR" not in _format_context(sources)
