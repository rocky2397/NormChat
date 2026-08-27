"""Query expansion for BM25, and the lexical index it reads from.

German compounding defeats exact-token matching: an engineer asks about
"Querkraftbemessung" and the clause is headed "Querkraft".
"""

import pytest

from services.reranking import _expand_compounds, _get_lexical_index, bm25_rank_ids


@pytest.fixture(autouse=True)
def _clear_index_cache():
    # The index is cached with maxsize=1, so tests would otherwise inherit
    # whichever corpus ran last.
    _get_lexical_index.cache_clear()
    yield
    _get_lexical_index.cache_clear()


class TestCompoundExpansion:
    def test_german_compound_is_expanded_to_corpus_words(self):
        # "Querkraftbemessung" shares no token with the clause heading
        # "Querkraft"; measured to move the EN 1992-1-1 §6.2 chunks from
        # BM25 rank 281 to rank 22.
        vocabulary = {"querkraft", "bemessung", "stahlbeton", "schnee"}
        expanded = _expand_compounds(["querkraftbemessung"], vocabulary)
        assert "querkraft" in expanded and "bemessung" in expanded
        assert "schnee" not in expanded

    def test_short_tokens_are_left_alone(self):
        assert _expand_compounds(["querkraft"], {"kraft", "quer"}) == ["querkraft"]

    def test_original_tokens_are_always_kept(self):
        assert "querkraftbemessung" in _expand_compounds(["querkraftbemessung"], {"querkraft"})


class TestDeterminism:
    def test_equal_length_candidates_are_ordered_alphabetically(self):
        # Sorting on length alone left ties in set iteration order, which
        # Python randomises per process: which parts survived the cut changed
        # between runs, so the same question returned different sources and
        # probe measurements moved without any change being made.
        vocabulary = {"querkraft", "bemessung", "kraftbeme", "stahlbeton"}
        expanded = _expand_compounds(["querkraftbemessung"], vocabulary)
        assert expanded == ["querkraftbemessung", "bemessung", "kraftbeme", "querkraft"]

    def test_result_does_not_depend_on_set_construction_order(self):
        words = ["querkraft", "bemessung", "kraftbeme"]
        first = _expand_compounds(["querkraftbemessung"], set(words))
        second = _expand_compounds(["querkraftbemessung"], set(reversed(words)))
        assert first == second


# Three documents, not two: BM25 idf is log(N-n+0.5) - log(n+0.5), which is
# exactly 0 for a term in one of two documents, so every score ties and the
# assertions would pass on sort order rather than on relevance.
IDS = ["shear", "snow", "fire"]
DOCS = [
    "6.2.3 Querkraft und Querkraftbewehrung im Stahlbetonbalken",
    "Schneelast auf dem Dach und Formbeiwert",
    "Abbrandtiefe und Restquerschnitt bei Holzbauteilen",
]


class TestLexicalIndexCache:
    """The index tokenizes the whole corpus, so it is built once per corpus
    rather than once per query — with expansion on it was rebuilt five times
    for a single request."""

    def test_repeated_queries_over_one_corpus_build_it_once(self):
        bm25_rank_ids("Querkraft", IDS, DOCS)
        builds = _get_lexical_index.cache_info().misses
        for query in ("Schnee", "Bewehrung", "Dach", "Querkraft"):
            bm25_rank_ids(query, IDS, DOCS)
        assert _get_lexical_index.cache_info().misses == builds

    def test_a_changed_corpus_is_not_served_from_the_cache(self):
        # An ingest changes the ids, which is what has to invalidate it —
        # a stale index would keep ranking a corpus that no longer exists.
        assert bm25_rank_ids("Querkraft", IDS[:2], DOCS[:2]) == IDS[:2]
        builds = _get_lexical_index.cache_info().misses
        assert sorted(bm25_rank_ids("Querkraft", IDS, DOCS)) == sorted(IDS)
        assert _get_lexical_index.cache_info().misses == builds + 1

    def test_compound_expansion_still_reads_the_corpus_vocabulary(self):
        # The vocabulary now comes off the cached index; "Querkraftbemessung"
        # shares no token with either document and is only reachable through
        # the "querkraft" the corpus supplies.
        assert bm25_rank_ids("Querkraftbemessung", IDS, DOCS)[0] == "shear"

    def test_every_id_is_returned_exactly_once(self):
        assert sorted(bm25_rank_ids("Querkraft", IDS, DOCS)) == sorted(IDS)

    def test_empty_corpus_is_handled_before_the_index_is_built(self):
        assert bm25_rank_ids("Querkraft", [], []) == []
        assert _get_lexical_index.cache_info().misses == 0


class TestLexicalIndexMemory:
    """The cache used to key on the corpus itself, which kept it alive.

    An `lru_cache` on (ids, documents) retains a reference to every chunk
    string it was built from. The next query pulled a fresh copy of the corpus
    out of Chroma while the previous copy was still reachable through that
    key, so two full corpora sat in memory at once -- what took the second
    query of a session over a 2 GB instance limit on the DIN corpus.
    """

    def test_chunk_text_is_released_once_the_caller_drops_it(self):
        import gc
        import weakref

        class _Chunk(str):
            """`str` subclasses are weak-referenceable; plain `str` is not."""

        documents = [_Chunk(text) for text in DOCS]
        witnesses = [weakref.ref(document) for document in documents]

        bm25_rank_ids("Querkraft", IDS, documents)

        del documents
        gc.collect()

        assert [witness() for witness in witnesses] == [None] * len(DOCS)

    def test_enriched_text_under_unchanged_ids_still_rebuilds(self):
        # Reference enrichment rewrites a chunk's indexed text in place and
        # leaves its id alone, so ids alone cannot identify a corpus. Serving
        # the stale index here would rank text that no longer exists.
        bm25_rank_ids("Querkraft", IDS, DOCS)
        builds = _get_lexical_index.cache_info().misses

        enriched = list(DOCS)
        enriched[0] = f"{DOCS[0]} — Festlegung zu Abschnitt 6.2.3"
        bm25_rank_ids("Querkraft", IDS, enriched)

        assert _get_lexical_index.cache_info().misses == builds + 1

    def test_identical_text_under_identical_ids_is_served_from_the_slot(self):
        bm25_rank_ids("Querkraft", IDS, DOCS)
        builds = _get_lexical_index.cache_info().misses
        # A separate list with equal content is the same corpus.
        bm25_rank_ids("Querkraft", list(IDS), list(DOCS))
        assert _get_lexical_index.cache_info().misses == builds
