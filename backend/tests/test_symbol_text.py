"""Symbol-font glyph recovery.

The norm PDFs these paths exist for are copyrighted and not in the repo, so
these tests drive the pure logic with synthetic inputs. The document-level
behaviour was verified separately against the real corpus by rendering the
page and comparing it to the decoded text.
"""

import pytest

from services.pdf_highlight import _split_at_symbols
from services.symbol_text import (
    ADOBE_SYMBOL,
    GID_TO_SYMBOL_CODE_OFFSET,
    _RESIDUAL_CONTROL,
    _is_symbol_font,
)


class TestAdobeSymbolTable:
    def test_greek_letters_used_in_norm_formulas_are_mapped(self):
        # f_cd = alpha_cc * f_ck / gamma_C, and the stress/strain pair.
        assert ADOBE_SYMBOL[0x61] == "α"
        assert ADOBE_SYMBOL[0x67] == "γ"
        assert ADOBE_SYMBOL[0x73] == "σ"
        assert ADOBE_SYMBOL[0x65] == "ε"

    def test_glyph_id_offset_resolves_alpha_and_gamma(self):
        # The two mappings confirmed against rendered glyphs in
        # ÖNORM EN 1992-1-1: /g68 is alpha, /g74 is gamma.
        assert ADOBE_SYMBOL[68 + GID_TO_SYMBOL_CODE_OFFSET] == "α"
        assert ADOBE_SYMBOL[74 + GID_TO_SYMBOL_CODE_OFFSET] == "γ"

    def test_no_private_use_characters_leak_into_the_table(self):
        # Bracket/integral assembly pieces carry no textual meaning; if one
        # were mapped it would end up in chunk text and in embeddings.
        assert not [c for c in ADOBE_SYMBOL.values() if 0xE000 <= ord(c) <= 0xF8FF]


class TestResidualControlPattern:
    def test_layout_whitespace_is_preserved(self):
        assert _RESIDUAL_CONTROL.sub("", "a\nb\tc\rd") == "a\nb\tc\rd"

    def test_unresolved_glyph_codes_are_removed(self):
        assert _RESIDUAL_CONTROL.sub("", "fcd = \x06cc fck / \x03C") == "fcd = cc fck / C"

    @pytest.mark.parametrize("font,expected", [
        ("ANONLP+SymbolMT", True),
        ("AHDDKI+Symbol", True),
        ("ANOMLA+ArialMT", False),
        ("TimesNewRomanPSMT", False),
    ])
    def test_only_symbol_fonts_are_translated(self, font, expected):
        assert _is_symbol_font(font) is expected


class TestHighlightFragments:
    def test_splits_around_a_recovered_symbol(self):
        # The page's text layer still holds control characters where the
        # Greek letters are, so only the surrounding runs can be searched.
        fragments = _split_at_symbols(
            "Der Bemessungswert betraegt αcc mal fck geteilt durch γC hier"
        )
        assert "Der Bemessungswert betraegt" in fragments
        assert all("α" not in f and "γ" not in f for f in fragments)

    def test_longest_fragment_comes_first(self):
        fragments = _split_at_symbols(
            "kurzer teil hier ok α ein deutlich laengerer textabschnitt folgt"
        )
        assert fragments == sorted(fragments, key=len, reverse=True)

    def test_short_fragments_are_dropped(self):
        # Too-short strings match all over a page and would highlight noise.
        assert _split_at_symbols("αβγ") == []

    def test_plain_text_is_returned_unchanged(self):
        text = "Ein Absatz ganz ohne Sonderzeichen aus der Norm"
        assert _split_at_symbols(text) == [text]
