"""Query expansion for BM25.

German compounding defeats exact-token matching: an engineer asks about
"Querkraftbemessung" and the clause is headed "Querkraft".
"""

from services.reranking import _expand_compounds


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
