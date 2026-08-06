"""Front-matter stripping before chunking.

Motivated by a measured failure, not a hunch: covers, contents pages and
forewords outranked the operative clauses in three of five reference
questions (eval/runs/2026-08-06-baseline.md).
"""

from services.chunking import PageText, strip_front_matter

COVER = (
    "Medieninhaber und Hersteller\nAustrian Standards Institute\n"
    "Copyright © Austrian Standards Institute 2018\nÖNORM\nB 1992-1-1"
)
CONTENTS = "\n".join(
    ["Inhalt", "Vorwort..............................4"]
    + [f"{i} Abschnitt {i}...............................{i+3}" for i in range(1, 10)]
)
FOREWORD_THEN_CLAUSES = (
    "Vorwort\n"
    "Im Eurocode ÖNORM EN 1992-1-1 wurden für nationale Entscheidungen "
    "Angaben zu Parametern offen gelassen.\n"
    "1 Anwendungsbereich\n"
    "Diese ÖNORM gilt für den Entwurf von Tragwerken aus Beton.\n"
    "2 Normative Verweisungen\n"
    "ÖNORM B 4707, Bewehrungsstahl"
)


def _pages(*texts):
    return [PageText(page_number=i, text=t) for i, t in enumerate(texts, start=1)]


class TestStripFrontMatter:
    def test_cover_page_is_blanked(self):
        assert strip_front_matter(_pages(COVER))[0].text == ""

    def test_contents_page_is_blanked(self):
        result = strip_front_matter(_pages("body text", CONTENTS))
        assert result[1].text == ""

    def test_foreword_is_kept_because_it_states_document_relationships(self):
        # Tried and reverted: removing forewords made Q1 of the eval set
        # regress from a correct description of the EN/B relationship to an
        # invented one, because the foreword is where that relationship is
        # stated. Pinned so it is not "cleaned up" again.
        text = strip_front_matter(_pages(FOREWORD_THEN_CLAUSES))[0].text
        assert "nationale Entscheidungen" in text
        assert "1 Anwendungsbereich" in text

    def test_page_numbers_are_preserved(self):
        # Citations point at physical pages; blanking must not renumber.
        result = strip_front_matter(_pages(COVER, CONTENTS, "6.1.4 Festlegung"))
        assert [p.page_number for p in result] == [1, 2, 3]
        assert result[2].text == "6.1.4 Festlegung"

    def test_ordinary_body_page_is_untouched(self):
        body = "6.2 Querkraft\nDie Bemessung erfolgt nach Gleichung (6.2)."
        assert strip_front_matter(_pages(body))[0].text == body

    def test_cover_marker_on_a_later_page_is_not_treated_as_a_cover(self):
        # Only page 1 can be a cover; a copyright note in a footnote later in
        # the document must not blank a page of real content.
        pages = _pages("body", "Copyright © Austrian Standards Institute 2018\n6.1 Abbrandtiefe")
        assert "Abbrandtiefe" in strip_front_matter(pages)[1].text
