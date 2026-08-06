"""Recovery of Symbol-font glyphs that PDF text extraction returns as control
characters.

Norm PDFs typeset Greek letters and math operators in a subsetted `SymbolMT`
font that carries no usable ToUnicode CMap. MuPDF then falls back to raw
glyph codes, so `f_cd = α_cc · f_ck / γ_C` extracts as
`fcd = \\x06cc fck / \\x03C` — the letters look "dropped" because C0 control
characters are invisible, but they are present and they poison everything
downstream: embeddings and BM25 see garbage tokens, and PyMuPDF's
`search_for()` fails outright on any string containing them, which silently
breaks in-PDF highlighting.

The identity of each glyph is recoverable. The font's `/Encoding`
`/Differences` array names glyphs `/g74`, `/g68` … — opaque subset names, but
the numbers are glyph IDs in the *original* SymbolMT, and those sit at a fixed
offset from the Adobe Symbol character codes, which do map to Unicode.
"""

import re

import fitz  # PyMuPDF

# Adobe Symbol encoding: character code -> Unicode. Greek letters plus the
# math operators that appear in norm text; the private-use box-drawing pieces
# (bracket and integral segments) are deliberately absent — they carry no
# meaning in extracted text and are better dropped than transliterated.
ADOBE_SYMBOL: dict[int, str] = {
    0x22: "∀", 0x24: "∃", 0x27: "∋", 0x2A: "∗", 0x2D: "−",
    0x40: "≅",
    0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε", 0x46: "Φ",
    0x47: "Γ", 0x48: "Η", 0x49: "Ι", 0x4A: "ϑ", 0x4B: "Κ", 0x4C: "Λ",
    0x4D: "Μ", 0x4E: "Ν", 0x4F: "Ο", 0x50: "Π", 0x51: "Θ", 0x52: "Ρ",
    0x53: "Σ", 0x54: "Τ", 0x55: "Υ", 0x56: "ς", 0x57: "Ω", 0x58: "Ξ",
    0x59: "Ψ", 0x5A: "Ζ",
    0x5C: "∴", 0x5E: "⊥",
    0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ",
    0x67: "γ", 0x68: "η", 0x69: "ι", 0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ",
    0x6D: "μ", 0x6E: "ν", 0x6F: "ο", 0x70: "π", 0x71: "θ", 0x72: "ρ",
    0x73: "σ", 0x74: "τ", 0x75: "υ", 0x76: "ϖ", 0x77: "ω", 0x78: "ξ",
    0x79: "ψ", 0x7A: "ζ",
    0x7E: "∼",
    0xA1: "ϒ", 0xA2: "′", 0xA3: "≤", 0xA4: "⁄", 0xA5: "∞", 0xA6: "ƒ",
    0xAB: "↔", 0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓",
    0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝",
    0xB6: "∂", 0xB7: "•", 0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈",
    0xBC: "…",
    0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩", 0xC8: "∪", 0xC9: "⊃",
    0xCA: "⊇", 0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆", 0xCE: "∈", 0xCF: "∉",
    0xD0: "∠", 0xD1: "∇", 0xD5: "∏", 0xD6: "√", 0xD7: "⋅", 0xD8: "¬",
    0xD9: "∧", 0xDA: "∨", 0xDB: "⇔", 0xDC: "⇐", 0xDD: "⇑", 0xDE: "⇒",
    0xDF: "⇓",
    0xE0: "◊", 0xE1: "⟨", 0xE5: "∑", 0xF1: "⟩", 0xF2: "∫",
}

# Derived empirically and confirmed against rendered glyphs: in
# ÖNORM EN 1992-1-1 the encoding maps code 6 -> /g68 and code 3 -> /g74, and
# rendering that page shows α and γ respectively. Adobe Symbol puts alpha at
# 0x61 (97) and gamma at 0x67 (103) — both exactly 29 above the glyph id.
# To re-verify on a new document: render the page region with
# `page.get_pixmap(clip=...)` and compare against the decoded text.
GID_TO_SYMBOL_CODE_OFFSET = 29

_GLYPH_ID_NAME = re.compile(r"^/?g(\d+)$")
_ENCODING_REF = re.compile(r"/Encoding\s+(\d+)\s+0\s+R")
_DIFFERENCES = re.compile(r"/Differences\s*\[(.*?)\]", re.S)

# Newline/tab carry layout meaning; every other C0 code (and DEL) is an
# unresolved glyph rather than text.
_RESIDUAL_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _is_unresolved_code(code: int) -> bool:
    # Codes are parsed out of the PDF, so a malformed /Differences array must
    # not take ingestion down with a ValueError from chr().
    return 0 <= code < 0x80 and bool(_RESIDUAL_CONTROL.match(chr(code)))


def _is_symbol_font(basename: str) -> bool:
    # Restricting to Symbol-named fonts keeps the translation away from
    # ordinary text fonts, where a control character means something else
    # (or nothing) and guessing would corrupt real content.
    return "Symbol" in basename


def build_symbol_maps(doc: fitz.Document) -> dict[str, dict[int, str]]:
    """Maps each Symbol font in the document to {extracted code: character}.

    Subsets are per-font, not per-document: ÖNORM EN 1992-1-1 alone embeds
    seven different SymbolMT subsets with independent code assignments.
    """
    maps: dict[str, dict[int, str]] = {}
    for pno in range(doc.page_count):
        for font_info in doc[pno].get_fonts(full=True):
            xref, basename = font_info[0], font_info[3]
            if basename in maps or not _is_symbol_font(basename):
                continue

            encoding_ref = _ENCODING_REF.search(doc.xref_object(xref))
            if not encoding_ref:
                continue
            differences = _DIFFERENCES.search(doc.xref_object(int(encoding_ref.group(1))))
            if not differences:
                continue

            table: dict[int, str] = {}
            code = 0
            for token in differences.group(1).split():
                if token.isdigit():
                    code = int(token)
                    continue
                glyph_id = _GLYPH_ID_NAME.match(token)
                # Only codes that extract as control characters are recorded.
                # A Symbol subset also assigns codes in the printable ASCII
                # range, but page text is a single string with no font
                # attribution, so translating those would rewrite ordinary
                # letters drawn in Arial or Times on the same page. Control
                # characters are unambiguous: no text font produces them.
                if glyph_id and _is_unresolved_code(code):
                    symbol_code = int(glyph_id.group(1)) + GID_TO_SYMBOL_CODE_OFFSET
                    if symbol_code in ADOBE_SYMBOL:
                        table[code] = ADOBE_SYMBOL[symbol_code]
                code += 1

            if table:
                maps[basename] = table
    return maps


def _page_font_maps(
    page: fitz.Page, maps: dict[str, dict[int, str]]
) -> dict[str, dict[int, str]]:
    names = {info[3] for info in page.get_fonts(full=True)}
    return {name: table for name, table in maps.items() if name in names}


def _lookup(font: str, active: dict[str, dict[int, str]]) -> dict[int, str] | None:
    # Span font names are the un-prefixed form ("SymbolMT") of the document
    # font name ("ANONLP+SymbolMT").
    for name, table in active.items():
        if name == font or name.endswith(font):
            return table
    return None


def _decode_per_span(page: fitz.Page, active: dict[str, dict[int, str]]) -> str:
    """Rebuilds page text span by span so each glyph is resolved against the
    font that actually drew it. Only used when two subsets on one page
    disagree about a code, since reassembly does not reproduce `get_text()`
    layout exactly.
    """
    lines: list[str] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            parts = []
            for span in line["spans"]:
                table = _lookup(span["font"], active)
                text = span["text"]
                if table:
                    text = "".join(table.get(ord(ch), ch) for ch in text)
                parts.append(text)
            lines.append("".join(parts))
        if block.get("lines"):
            lines.append("")
    return "\n".join(lines)


def extract_page_text(page: fitz.Page, maps: dict[str, dict[int, str]]) -> str:
    """Page text with Symbol-font glyphs resolved and unresolved ones removed.

    Uses `get_text()` unchanged wherever possible — layout affects boilerplate
    detection and chunk boundaries, so pages that need no repair must come
    through byte-identical.
    """
    text = page.get_text()
    if not _RESIDUAL_CONTROL.search(text):
        return text

    active = _page_font_maps(page, maps)
    if active:
        by_code: dict[int, set[str]] = {}
        for table in active.values():
            for code, char in table.items():
                by_code.setdefault(code, set()).add(char)

        if any(len(chars) > 1 for chars in by_code.values()):
            text = _decode_per_span(page, active)
        else:
            text = text.translate({code: chars.pop() for code, chars in by_code.items()})

    # Whatever is still a control character belongs to a font this module
    # cannot resolve. Dropping it is deliberate: a wrong Greek letter changes
    # the meaning of a formula, and leaving it in breaks `search_for()`.
    return _RESIDUAL_CONTROL.sub("", text)
