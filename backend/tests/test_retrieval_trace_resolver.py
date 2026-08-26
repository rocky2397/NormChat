"""Parsing `trace-gold` blocks and resolving them to chunk ids.

Expected sources are (norm_reference, page, clause) triples rather than
Chroma ids, because ids embed a per-ingestion document id and would not
survive a re-ingest (see the module docstring in services.retrieval_trace).
The resolver is what turns a triple back into the chunk(s) it names, against
the corpus actually loaded for one project.
"""

import pytest

from services.retrieval_trace import (
    QUESTIONS_FILE,
    ExpectedSource,
    UnresolvedExpectedSourceError,
    parse_expected_sources,
    parse_questions,
    resolve_expected_source,
)

SAMPLE = """# Some file

## Q1

> Welche Normen gelten?

```trace-gold
ÖNORM EN 1995-1-2: *
ÖNORM B 1995-1-2: *
```

## Q3

> Erläutere mir die Querkraftbemessung eines Stahlbetonbalkens.

```trace-gold
ÖNORM EN 1992-1-1: 93: 6.2
ÖNORM B 1992-1-1: 21: 9.2
```

## Q9

> A question with no trace-gold block yet.
"""


class TestParseExpectedSources:
    def test_reads_page_and_clause(self):
        section = SAMPLE.split("## Q3")[1]
        sources = parse_expected_sources(section)
        assert sources == (
            ExpectedSource("ÖNORM EN 1992-1-1", 93, "6.2"),
            ExpectedSource("ÖNORM B 1992-1-1", 21, "9.2"),
        )

    def test_star_page_is_document_level_with_no_clause(self):
        section = SAMPLE.split("## Q1")[1].split("## Q3")[0]
        sources = parse_expected_sources(section)
        assert sources == (
            ExpectedSource("ÖNORM EN 1995-1-2", None, None),
            ExpectedSource("ÖNORM B 1995-1-2", None, None),
        )

    def test_missing_block_is_empty(self):
        section = SAMPLE.split("## Q9")[1]
        assert parse_expected_sources(section) == ()

    def test_malformed_line_is_an_error_not_a_silent_skip(self):
        broken = "```trace-gold\nÖNORM B 1992-1-1 p. 21\n```"
        with pytest.raises(ValueError):
            parse_expected_sources(broken)

    def test_typeset_reference_variants_are_normalized(self):
        section = "```trace-gold\nÖNORM B 1992‑1-1: 21: 9.2\n```"
        (source,) = parse_expected_sources(section)
        assert source.norm_reference == "ÖNORM B 1992-1-1"


class TestParseQuestions:
    def test_only_sections_with_a_trace_gold_block_are_returned(self):
        questions = parse_questions(SAMPLE)
        assert [q.number for q in questions] == [1, 3]

    def test_question_text_and_expected_sources_are_read(self):
        questions = parse_questions(SAMPLE)
        q3 = next(q for q in questions if q.number == 3)
        assert q3.text == "Erläutere mir die Querkraftbemessung eines Stahlbetonbalkens."
        assert q3.expected == (
            ExpectedSource("ÖNORM EN 1992-1-1", 93, "6.2"),
            ExpectedSource("ÖNORM B 1992-1-1", 21, "9.2"),
        )

    def test_the_committed_question_set_parses(self):
        # The real file is the CLI's actual input; if its trace-gold blocks
        # and this parser drift apart, the CLI dies at run time in front of a
        # project that took an hour to ingest.
        questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))
        by_number = {q.number: q for q in questions}
        assert set(by_number) == {1, 2, 3, 4, 5, 6, 7}
        assert ExpectedSource("ÖNORM EN 1992-1-1", 93, "6.2") in by_number[3].expected
        assert ExpectedSource("ÖNORM B 1992-1-1", 21, "9.2") in by_number[3].expected
        # Q1, Q6, Q7 omit the clause: document-level or table/figure sources
        # have no single clause number to search for.
        assert all(s.clause is None for s in by_number[1].expected)
        assert all(s.clause is None for s in by_number[6].expected)
        assert all(s.clause is None for s in by_number[7].expected)


def _meta(reference, page, document_id="doc"):
    return {"document_id": document_id, "norm_reference": reference, "page_number": page}


ID_TO_META = {
    "en_62": _meta("ÖNORM EN 1992-1-1", 97, "en"),
    "en_31": _meta("ÖNORM EN 1992-1-1", 36, "en"),
    "b_92": _meta("ÖNORM B 1992-1-1", 21, "b"),
}
ID_TO_TEXT = {
    "en_62": "6.2.3 Querkraft\nBauteile mit rechnerisch erforderlicher Querkraftbewehrung.",
    "en_31": "3.1.6 Bemessungswert der Betondruckfestigkeit\n(1)P Der Bemessungswert.",
    "b_92": "9.2 Festlegung zu ÖNORM EN 1992-1-1, Abschnitt 6.2.3(2)\nDer empfohlene Wert.",
}


class TestResolveExpectedSource:
    def test_resolves_document_page_and_clause(self):
        expected = ExpectedSource("ÖNORM EN 1992-1-1", 97, "6.2")
        assert resolve_expected_source(expected, ID_TO_META, ID_TO_TEXT) == ("en_62",)

    def test_wrong_document_is_not_a_match_even_with_the_same_page_and_clause(self):
        # B 1992-1-1 p. 21 states "Abschnitt 6.2.3", so a clause-only match
        # would wrongly resolve the EN's own §6.2.3 against the annex.
        expected = ExpectedSource("ÖNORM EN 1992-1-1", 21, "6.2")
        with pytest.raises(UnresolvedExpectedSourceError):
            resolve_expected_source(expected, ID_TO_META, ID_TO_TEXT)

    def test_document_level_label_matches_any_page_of_that_document(self):
        expected = ExpectedSource("ÖNORM EN 1992-1-1", None, None)
        assert set(resolve_expected_source(expected, ID_TO_META, ID_TO_TEXT)) == {
            "en_62",
            "en_31",
        }

    def test_page_only_label_ignores_clause_text(self):
        expected = ExpectedSource("ÖNORM B 1992-1-1", 21, None)
        assert resolve_expected_source(expected, ID_TO_META, ID_TO_TEXT) == ("b_92",)

    def test_clause_absent_from_the_chunk_text_is_not_a_match(self):
        expected = ExpectedSource("ÖNORM EN 1992-1-1", 97, "9.9")
        with pytest.raises(UnresolvedExpectedSourceError):
            resolve_expected_source(expected, ID_TO_META, ID_TO_TEXT)

    def test_no_matching_chunk_anywhere_fails_loudly(self):
        # This is the case the resolver exists to catch: a wrong label or an
        # incomplete corpus must not silently become "zero recall", which
        # would be indistinguishable from a genuine retrieval miss.
        expected = ExpectedSource("ÖNORM EN 1997-1-1", 5, "2.1")
        with pytest.raises(UnresolvedExpectedSourceError, match="ÖNORM EN 1997-1-1"):
            resolve_expected_source(expected, ID_TO_META, ID_TO_TEXT)

    def test_clause_number_boundaries_do_not_bleed_into_neighbours(self):
        # "6.2" must not match inside "16.2" or "6.23".
        id_to_text = {"x": "16.2 Vorwort\n6.23 anderes Thema"}
        id_to_meta = {"x": _meta("ÖNORM EN 1992-1-1", 1, "en")}
        expected = ExpectedSource("ÖNORM EN 1992-1-1", 1, "6.2")
        with pytest.raises(UnresolvedExpectedSourceError):
            resolve_expected_source(expected, id_to_meta, id_to_text)
