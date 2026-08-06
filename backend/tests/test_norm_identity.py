"""Norm document identity parsing.

Driven with synthetic cover text: the real PDFs are copyrighted and
gitignored, so the corpus cannot be a fixture. Parsing was checked against
all 39 documents separately (39/39 resolved, no colliding keys).
"""

from services.norm_identity import (
    NormIdentity,
    normalize_reference_text,
    parse_identity,
)
from services.storage import extract_norm_reference

EN_COVER = "ÖNORM\nEN 1992-1-1\nAusgabe: 2015-02-15\nEurocode 2: Bemessung ..."
B_COVER = "ÖNORM\nB 1995-1-2\nAusgabe: 2011-09-01\nEurocode 5: Holzbauten ..."
AMENDMENT_COVER = "ÖNORM\nEN 1990/A1\nAusgabe: 2013-03-15\nÄnderung 1: Brücken"


class TestNormalizeReferenceText:
    def test_non_breaking_space_becomes_a_plain_space(self):
        assert normalize_reference_text("ÖNORM EN 1992-1-1") == "ÖNORM EN 1992-1-1"

    def test_non_breaking_hyphen_becomes_a_plain_hyphen(self):
        assert normalize_reference_text("EN 1992‑1‑1") == "EN 1992-1-1"

    def test_reference_wrapped_across_lines_is_rejoined(self):
        assert normalize_reference_text("ÖNORM \nEN  1992-1-1") == "ÖNORM EN 1992-1-1"


class TestParseIdentity:
    def test_adopted_european_norm(self):
        identity = parse_identity("whatever.pdf", EN_COVER)
        assert identity == NormIdentity(
            publisher="ÖNORM", designation="EN 1992-1-1", number="1992-1-1",
            national_annex=False, amendment=None, edition="2015-02-15",
            jurisdiction="AT",
        )
        assert identity.reference == "ÖNORM EN 1992-1-1"

    def test_national_supplement(self):
        # Austria publishes its national annex as a separate B series, where
        # Germany appends /NA to the same number.
        identity = parse_identity("whatever.pdf", B_COVER)
        assert identity.national_annex is True
        assert identity.reference == "ÖNORM B 1995-1-2"

    def test_amendment_is_distinct_from_the_norm_it_amends(self):
        # The bug this fixes: both used to resolve to "EN 1990".
        amendment = parse_identity("x.pdf", AMENDMENT_COVER)
        base = parse_identity("y.pdf", "ÖNORM\nEN 1990\nAusgabe: 2013-03-15")
        assert amendment.amendment == "A1"
        assert amendment.reference == "ÖNORM EN 1990/A1"
        assert amendment.key != base.key

    def test_identity_block_is_found_anywhere_on_the_cover(self):
        # The 2018 ÖNORM B layout prints the copyright block first and the
        # identity block at the foot of page 1.
        cover = "Medieninhaber und Hersteller\nAustrian Standards\n...\nÖNORM\nB 1992-1-1\nAusgabe: 2018-01-01"
        assert parse_identity("x.pdf", cover).reference == "ÖNORM B 1992-1-1"

    def test_superseded_edition_on_the_cover_is_not_mistaken_for_identity(self):
        cover = "Ersatz für ÖNORM B 1992-1-1:2011-12\nÖNORM\nB 1992-1-1\nAusgabe: 2018-01-01"
        assert parse_identity("x.pdf", cover).edition == "2018-01-01"

    def test_typeset_dirt_in_the_cover_still_parses(self):
        cover = "ÖNORM \n\nEN 1992‑1‑1 \n\nAusgabe: 2015-02-15"
        assert parse_identity("x.pdf", cover).reference == "ÖNORM EN 1992-1-1"

    def test_falls_back_to_the_filename_when_the_cover_yields_nothing(self):
        identity = parse_identity("OENORM_EN_1990_A1_2013_03_15_de.pdf", "")
        assert identity.reference == "ÖNORM EN 1990/A1"
        assert identity.edition == "2013-03-15"

    def test_unrecognised_document_has_no_identity(self):
        assert parse_identity("random.pdf", "Some unrelated document") is None


DIN_COVER = "Oktober 2021\nDEUTSCHE NORM\nICS 91.010.30\nwww.din.de\nDIN EN 1990\nEurocode: Grundlagen der Tragwerksplanung;"
DIN_NA_COVER = "Dezember 2010\nDEUTSCHE NORM\nwww.din.de\nD\nDIN EN 1990/NA\nNationaler Anhang –\nNational festgelegte Parameter –"
DIN_NA_A1_COVER = "August 2012\nDEUTSCHE NORM\nwww.din.de\nD\nDIN EN 1990/NA/A1\nNationaler Anhang –\nÄnderung A1"
DIN_CORRIGENDUM_COVER = "Februar 2013\nDEUTSCHE NORM\nDIN EN 1991-3 Berichtigung 1\nBerichtigung zu DIN EN 1991-3:2010-12;"


class TestGermanIdentity:
    def test_adopted_european_norm(self):
        identity = parse_identity("x.pdf", DIN_COVER)
        assert identity.reference == "DIN EN 1990"
        assert identity.national_annex is False
        assert identity.edition == "2021-10"
        assert identity.jurisdiction == "DE"

    def test_national_annex_is_distinct_from_its_parent(self):
        # The distinction the product depends on: DIN EN 1990 alone does not
        # state what applies in Germany.
        norm = parse_identity("x.pdf", DIN_COVER)
        annex = parse_identity("y.pdf", DIN_NA_COVER)
        assert annex.reference == "DIN EN 1990/NA"
        assert annex.national_annex is True
        assert norm.key != annex.key

    def test_amendment_to_a_national_annex(self):
        identity = parse_identity("x.pdf", DIN_NA_A1_COVER)
        assert identity.reference == "DIN EN 1990/NA/A1"
        assert identity.national_annex is True
        assert identity.amendment == "A1"

    def test_corrigendum(self):
        identity = parse_identity("x.pdf", DIN_CORRIGENDUM_COVER)
        assert identity.reference == "DIN EN 1991-3 Berichtigung 1"

    def test_a_norm_that_merely_mentions_its_annex_is_not_the_annex(self):
        # Regression: searching the flattened page for the longest match made
        # this resolve to the annex, collapsing 18 EN/NA pairs in the corpus.
        cover = "Oktober 2021\nDEUTSCHE NORM\nDIN EN 1991-1-1\nist gemeinsam mit DIN EN 1991-1-1/NA anzuwenden"
        identity = parse_identity("x.pdf", cover)
        assert identity.reference == "DIN EN 1991-1-1"
        assert identity.national_annex is False

    def test_filename_fallback_does_not_swallow_a_trailing_date(self):
        identity = parse_identity("DIN EN 1991-1-2-2010-12.pdf", "")
        assert identity.designation == "EN 1991-1-2"


class TestExtractNormReferenceFallback:
    def test_recognised_publisher_uses_the_structured_identity(self):
        assert extract_norm_reference("x.pdf", EN_COVER) == "ÖNORM EN 1992-1-1"
        assert extract_norm_reference("x.pdf", DIN_NA_COVER) == "DIN EN 1990/NA"

    def test_din_without_en_keeps_its_original_behaviour(self):
        # No profile matches a plain DIN number, so it falls through to the
        # legacy patterns. Those return the filename stem rather than
        # "DIN 4102-2" — the pattern reads DIN\s*EN?\s*\d+, where `EN?` needs
        # a literal E, so it only ever matched "DIN EN …". Pre-existing and
        # asserted here so the fallback path stays pinned, not endorsed.
        assert extract_norm_reference("din_4102_2.pdf", "DIN 4102-2 Brandverhalten") == "din_4102_2"

    def test_unknown_document_still_falls_back_to_the_filename_stem(self):
        assert extract_norm_reference("hausordnung.pdf", "kein Normtext") == "hausordnung"
