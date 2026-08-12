"""Table serialisation.

Flattened grids lose row membership: asked for the concrete cover in
exposure class XC4, the tool read 15 mm from the S1 row of Tabelle 4.4N
while the question concerned S4 (30 mm). These tests drive the pure
serialisation logic; detection against real PDFs was verified separately,
since the corpus is copyrighted and gitignored.
"""

from services.tables import (
    CAPTION_PATTERN,
    TableBlock,
    _caption_for,
    _clean_cell,
    _is_degenerate,
    _to_markdown,
    split_table_rows,
)

COVER_ROWS = [
    ["Anforderungsklasse", "X0", "XC1", "XC2/XC3", "XC4"],
    ["S1", "10", "10", "10", "15"],
    ["S4", "10", "15", "25", "30"],
]


class TestSerialisation:
    def test_row_membership_survives(self):
        # The whole point: XC4 must be recoverable as 30 for S4 and 15 for
        # S1, which reading order alone does not give.
        md = _to_markdown(COVER_ROWS)
        rows = {line.split("|")[1].strip(): line for line in md.split("\n")}
        assert rows["S4"].endswith("| 30 |")
        assert rows["S1"].endswith("| 15 |")

    def test_short_rows_are_padded_so_columns_stay_aligned(self):
        md = _to_markdown([["a", "b", "c"], ["1"], ["2", "3", "4"]])
        widths = {line.count("|") for line in md.split("\n")}
        assert len(widths) == 1

    def test_empty_cells_are_kept_not_dropped(self):
        # Dropping an empty cell shifts every value after it into the wrong
        # column, which is the failure mode being fixed.
        md = _to_markdown([["h1", "h2", "h3"], ["a", "", "c"]])
        assert md.split("\n")[-1] == "| a |  | c |"


class TestCellCleaning:
    def test_unresolved_symbol_glyphs_are_removed(self):
        # find_tables() bypasses services/symbol_text.py, so cells arrive
        # with the control characters Greek letters degrade to.
        assert _clean_cell("\x1a C30/37") == "C30/37"

    def test_newlines_collapse_so_a_cell_cannot_break_the_row(self):
        assert _clean_cell("Druckfestigkeits-\nklasse") == "Druckfestigkeits- klasse"

    def test_a_pipe_in_a_cell_cannot_fabricate_a_column(self):
        assert _clean_cell("a | b") == "a \\| b"

    def test_missing_cell_becomes_empty(self):
        assert _clean_cell(None) == ""


class TestDegenerateRejection:
    def test_single_column_is_rejected(self):
        assert _is_degenerate([["a"], ["b"]])

    def test_single_row_is_rejected(self):
        assert _is_degenerate([["a", "b"]])

    def test_all_empty_is_rejected(self):
        assert _is_degenerate([["", ""], ["", ""]])

    def test_a_real_grid_is_kept(self):
        assert not _is_degenerate(COVER_ROWS)


class TestCaptionAssignment:
    def test_nearest_caption_above_wins(self):
        # Tabelle 4.3N and 4.4N share a page; taking the first caption found
        # would label both grids with the same name.
        captions = [(120.0, "Tabelle 4.3N — Modifikation"), (530.0, "Tabelle 4.4N — Betondeckung")]
        assert _caption_for(533.0, captions).startswith("Tabelle 4.4N")
        assert _caption_for(125.0, captions).startswith("Tabelle 4.3N")

    def test_no_caption_above_yields_none(self):
        assert _caption_for(50.0, [(530.0, "Tabelle 4.4N")]) is None

    def test_pattern_matches_the_forms_norms_use(self):
        for caption in ("Tabelle 3.1", "Tabelle 4.4N", "Tabelle E.1N", "Tabelle 7.1DE"):
            assert CAPTION_PATTERN.search(caption), caption


class TestSplitting:
    def test_a_table_that_fits_is_not_split(self):
        md = _to_markdown(COVER_ROWS)
        assert split_table_rows(md, lambda _: True) == [md]

    def test_oversized_table_repeats_the_header(self):
        md = _to_markdown(COVER_ROWS)
        pieces = split_table_rows(md, lambda text: text.count("\n") < 3)
        assert len(pieces) > 1
        header = md.split("\n")[0]
        assert all(piece.startswith(header) for piece in pieces)

    def test_every_body_row_survives_exactly_once(self):
        md = _to_markdown(COVER_ROWS)
        pieces = split_table_rows(md, lambda text: text.count("\n") < 3)
        assert sum(p.count("| S1 |") for p in pieces) == 1
        assert sum(p.count("| S4 |") for p in pieces) == 1

    def test_unsplittable_shape_is_returned_whole(self):
        # Better one oversized chunk than a silently mangled grid.
        assert split_table_rows("no table here", lambda _: False) == ["no table here"]


class TestTableBlockText:
    def test_caption_leads_the_chunk(self):
        block = TableBlock(page_number=56, caption="Tabelle 4.4N", markdown="| a |")
        assert block.text.startswith("Tabelle 4.4N\n")

    def test_uncaptioned_table_is_just_the_grid(self):
        assert TableBlock(page_number=1, caption=None, markdown="| a |").text == "| a |"


class TestStackedHeaders:
    # Norm tables stack a merged title and a spanning group label above the
    # real column labels. Treating row 0 as the header made the exposure
    # classes read as data, and the tool answered 25 mm for XC4 — the
    # XC2/XC3 column — having miscounted from a header that was not one.
    STACKED = [
        ["Dauerhaftigkeitsanforderung für cmin,dur (mm)", "", "", "", ""],
        ["Anforderungsklasse", "Expositionsklasse nach Tabelle 4.1", "", "", ""],
        ["", "X0", "XC1", "XC2/XC3", "XC4"],
        ["S1", "10", "10", "10", "15"],
        ["S4", "10", "15", "25", "30"],
    ]

    def test_the_real_column_labels_become_the_header(self):
        md = _to_markdown(self.STACKED)
        header = next(line for line in md.split("\n") if line.startswith("|"))
        assert "XC4" in header and "X0" in header

    def test_the_first_column_label_is_filled_from_the_spanning_row(self):
        md = _to_markdown(self.STACKED)
        header = next(line for line in md.split("\n") if line.startswith("|"))
        assert header.startswith("| Anforderungsklasse |")

    def test_xc4_resolves_to_the_right_column(self):
        # The actual regression: S4 under XC4 is 30, not 25.
        md = _to_markdown(self.STACKED)
        lines = md.split("\n")
        header = [c.strip() for c in next(l for l in lines if l.startswith("|")).split("|")[1:-1]]
        s4 = [c.strip() for c in next(l for l in lines if l.startswith("| S4")).split("|")[1:-1]]
        assert s4[header.index("XC4")] == "30"

    def test_title_rows_are_kept_as_text_not_columns(self):
        md = _to_markdown(self.STACKED)
        assert md.split("\n")[0] == "Dauerhaftigkeitsanforderung für cmin,dur (mm)"

    def test_a_plain_single_header_table_is_unaffected(self):
        md = _to_markdown([["h1", "h2"], ["a", "b"]])
        assert md.split("\n")[0] == "| h1 | h2 |"
