"""Gold parsing, gold matching and rank reporting for the retrieval probe.

Gold labels are (norm_reference, page_number) pairs on purpose — Chroma ids
embed a per-ingestion document id and do not survive a re-ingest — so the
matching rules, in particular that the right page in the wrong document is
not a hit, are what make the probe's numbers mean anything.
"""

import pytest

from eval.retrieval_probe import (
    QUESTIONS_FILE,
    STAGES,
    GoldLabel,
    GoldResult,
    ProbeQuestion,
    QuestionResult,
    _parse_gold_block,
    chunk_matches_gold,
    first_gold_rank,
    parse_questions,
    recall_at,
    render_report,
)

SAMPLE = """# Some file

## Q1

> Welche Normen gelten?

Gold block: still TBD.

```gold
TBD
```

- **Grading:** whatever

## Q3

> Erläutere mir die Querkraftbemessung eines Stahlbetonbalkens in
> Österreich unter Berücksichtigung der aktuellen Normung.

```gold
ÖNORM EN 1992-1-1: 93, 97, 98
ÖNORM B 1992-1-1: 21
```
"""


class TestParseQuestions:
    def test_reads_number_text_and_gold_labels(self):
        questions = parse_questions(SAMPLE)
        assert [q.number for q in questions] == [1, 3]
        q3 = questions[1]
        assert q3.text == (
            "Erläutere mir die Querkraftbemessung eines Stahlbetonbalkens "
            "in Österreich unter Berücksichtigung der aktuellen Normung."
        )
        assert q3.gold == (
            GoldLabel("ÖNORM EN 1992-1-1", frozenset({93, 97, 98})),
            GoldLabel("ÖNORM B 1992-1-1", frozenset({21})),
        )

    def test_a_tbd_block_yields_no_gold_labels(self):
        questions = parse_questions(SAMPLE)
        assert questions[0].gold == ()

    def test_a_malformed_gold_line_is_an_error_not_a_silent_skip(self):
        broken = SAMPLE.replace("ÖNORM B 1992-1-1: 21", "ÖNORM B 1992-1-1 S. 21")
        with pytest.raises(ValueError):
            parse_questions(broken)

    def test_the_committed_question_set_parses(self):
        # The real file is the probe's actual input; if its gold blocks and
        # this parser drift apart, the probe dies at run time in front of a
        # project that took an hour to ingest.
        questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))
        by_number = {q.number: q for q in questions}
        # Q6 was added to cover tables, a content type the other five never
        # exercise; assert the set is contiguous rather than a fixed size, so
        # adding a question does not fail this test.
        assert set(by_number) == set(range(1, max(by_number) + 1))
        assert max(by_number) >= 5
        # Every question now carries gold. Q1 is document-level (`*`),
        # because it asks which norms apply rather than which clause does.
        assert all(by_number[n].gold for n in (1, 2, 3, 4, 5))
        assert all(label.pages is None for label in by_number[1].gold)
        for n in (3, 4, 5):
            assert by_number[n].gold, f"Q{n} should carry gold labels"
            assert by_number[n].text.startswith(("Erläutere", "Führe", "Muss"))
        assert GoldLabel("ÖNORM B 1992-1-1", frozenset({21})) in by_number[3].gold
        assert GoldLabel("ÖNORM B 1992-1-1", frozenset({28})) in by_number[4].gold
        assert GoldLabel("ÖNORM B 1992-1-1", frozenset({12})) in by_number[5].gold


GOLD_B21 = GoldLabel("ÖNORM B 1992-1-1", frozenset({21}))


def _meta(reference, page):
    return {"norm_reference": reference, "page_number": page}


class TestChunkMatchesGold:
    def test_right_document_right_page_is_a_hit(self):
        assert chunk_matches_gold(_meta("ÖNORM B 1992-1-1", 21), GOLD_B21)

    def test_right_page_in_the_wrong_document_is_not_a_hit(self):
        # EN 1992-1-1 p. 21 must not satisfy a gold label for B 1992-1-1
        # p. 21 — the two share clause numbering and vocabulary, and
        # conflating them is exactly what the question set exists to catch.
        assert not chunk_matches_gold(_meta("ÖNORM EN 1992-1-1", 21), GOLD_B21)

    def test_right_document_wrong_page_is_not_a_hit(self):
        assert not chunk_matches_gold(_meta("ÖNORM B 1992-1-1", 4), GOLD_B21)

    def test_typeset_reference_variants_still_match(self):
        # PDF metadata carries non-breaking spaces and hyphens; the same
        # norm must compare equal in all its byte forms.
        assert chunk_matches_gold(_meta("ÖNORM\u00a0B 1992\u20111-1", 21), GOLD_B21)

    def test_missing_metadata_is_not_a_hit(self):
        assert not chunk_matches_gold({}, GOLD_B21)
        assert not chunk_matches_gold({"norm_reference": "ÖNORM B 1992-1-1"}, GOLD_B21)


ID_TO_META = {
    "a": _meta("ÖNORM EN 1992-1-1", 93),
    "b": _meta("ÖNORM EN 1992-1-1", 21),
    "c": _meta("ÖNORM B 1992-1-1", 21),
}


class TestFirstGoldRank:
    def test_rank_is_one_based_position_of_first_match(self):
        assert first_gold_rank(["a", "b", "c"], ID_TO_META, GOLD_B21) == 3
        assert first_gold_rank(["c", "a"], ID_TO_META, GOLD_B21) == 1

    def test_no_match_is_none(self):
        assert first_gold_rank(["a", "b"], ID_TO_META, GOLD_B21) is None


def _result(number, ranks_per_gold):
    question = ProbeQuestion(number=number, text=f"Q{number}?", gold=())
    rows = [
        GoldResult(gold=gold, ranks=dict(ranks))
        for gold, ranks in ranks_per_gold
    ]
    return QuestionResult(question=question, rows=rows)


def _ranks(*values):
    """One rank per pipeline stage, in order.

    Taken from STAGES rather than restated, so adding a stage fails these
    tests loudly instead of silently dropping a column from the report.
    """
    assert len(values) == len(STAGES), f"expected {len(STAGES)} ranks, got {len(values)}"
    return dict(zip(STAGES, values))


RESULTS = [
    _result(3, [
        (GoldLabel("ÖNORM EN 1992-1-1", frozenset({93})), _ranks(4, 12, 3, 1, 1, 1)),
        (GoldLabel("ÖNORM B 1992-1-1", frozenset({21})), _ranks(None, 57, 80, None, None, None)),
    ]),
]


class TestRecallAndReport:
    def test_recall_counts_gold_labels_at_or_above_the_cutoff(self):
        assert recall_at(RESULTS, "dense", 10) == (1, 2)
        assert recall_at(RESULTS, "dense", 100) == (1, 2)
        assert recall_at(RESULTS, "fused", 100) == (2, 2)
        assert recall_at(RESULTS, "final", 10) == (1, 2)

    def test_report_shows_ranks_misses_recall_and_skips(self):
        report = render_report("proj-1", RESULTS, skipped=[1, 2], date_str="2026-08-07")
        assert "| Q3 | `ÖNORM B 1992-1-1` p. 21 | miss | 57 | 80 | miss | miss | miss |" in report
        assert "| Q3 | `ÖNORM EN 1992-1-1` p. 93 | 4 | 12 | 3 | 1 | 1 | 1 |" in report
        assert "| dense | 1/2 (0.50) | 1/2 (0.50) |" in report
        assert "| fused | 1/2 (0.50) | 2/2 (1.00) |" in report
        assert "Q1, Q2" in report


class TestDocumentLevelGold:
    def test_star_means_any_page(self):
        # Q1 asks which norms apply, so the expectation is that the document
        # reaches the context at all — pinning it to a page would measure
        # something the question never asks.
        (label,) = _parse_gold_block("```gold\nÖNORM EN 1995-1-2: *\n```")
        assert label.pages is None
        assert chunk_matches_gold(
            {"norm_reference": "ÖNORM EN 1995-1-2", "page_number": 77}, label
        )

    def test_star_still_requires_the_right_document(self):
        (label,) = _parse_gold_block("```gold\nÖNORM B 1995-1-2: *\n```")
        assert not chunk_matches_gold(
            {"norm_reference": "ÖNORM EN 1995-1-2", "page_number": 7}, label
        )

    def test_page_labels_are_unaffected(self):
        (label,) = _parse_gold_block("```gold\nÖNORM B 1995-1-2: 7\n```")
        assert label.pages == frozenset({7})
        assert not chunk_matches_gold(
            {"norm_reference": "ÖNORM B 1995-1-2", "page_number": 8}, label
        )
