"""Detection of several parts of one Eurocode family in the same answer.

EN 1992-1-1 recommends α_cc = 1,0 for buildings; EN 1992-2 recommends 0,85
for bridges. Both are correct in their own scope, and with both in context
the answer flipped between runs on context ordering alone
(eval/runs/2026-08-06-compound-expansion.md). The tool must contrast them
rather than pick.
"""

from models.chat import SourceChunk
from services.llm import _norm_part, _parts_in_conflict


def _source(norm_reference):
    return SourceChunk(
        document_id="d", filename="f.pdf", page_number=1,
        chunk_text="...", norm_reference=norm_reference,
    )


class TestNormPart:
    def test_reads_the_full_part_number(self):
        assert _norm_part("ÖNORM EN 1992-1-1") == "1992-1-1"
        assert _norm_part("ÖNORM EN 1992-2") == "1992-2"
        assert _norm_part("DIN EN 1990/NA") == "1990"

    def test_missing_reference_yields_nothing(self):
        assert _norm_part(None) is None


class TestPartsInConflict:
    def test_flags_two_parts_of_one_family(self):
        sources = [_source("ÖNORM EN 1992-1-1"), _source("ÖNORM EN 1992-2")]
        assert _parts_in_conflict(sources) == {"1992": ["1992-1-1", "1992-2"]}

    def test_a_national_annex_is_not_a_conflicting_part(self):
        # EN 1992-1-1 and B 1992-1-1 are the same part of the same family —
        # they are meant to be read together, not contrasted.
        sources = [_source("ÖNORM EN 1992-1-1"), _source("ÖNORM B 1992-1-1")]
        assert _parts_in_conflict(sources) == {}

    def test_different_families_are_not_a_conflict(self):
        sources = [_source("ÖNORM EN 1992-1-1"), _source("ÖNORM EN 1995-1-2")]
        assert _parts_in_conflict(sources) == {}

    def test_reports_every_family_that_spans_parts(self):
        sources = [
            _source("ÖNORM EN 1992-1-1"), _source("ÖNORM EN 1992-2"),
            _source("ÖNORM EN 1995-1-1"), _source("ÖNORM EN 1995-1-2"),
        ]
        assert _parts_in_conflict(sources) == {
            "1992": ["1992-1-1", "1992-2"],
            "1995": ["1995-1-1", "1995-1-2"],
        }

    def test_sources_without_a_reference_are_ignored(self):
        assert _parts_in_conflict([_source(None), _source("ÖNORM EN 1992-1-1")]) == {}
