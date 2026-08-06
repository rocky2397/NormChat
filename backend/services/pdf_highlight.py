import hashlib
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

from services.symbol_text import ADOBE_SYMBOL

_SYMBOL_CHARS = frozenset(ADOBE_SYMBOL.values())

_CACHE_DIR = Path(tempfile.gettempdir()) / "normchat_highlights"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _shrink_from_end(text: str, min_len: int = 20) -> list[str]:
    """Progressively drops trailing words. Handles a real failure mode seen
    in testing: an otherwise-good candidate whose tail hits an unmapped
    symbol-font glyph (e.g. a Greek letter that extracted as a stray
    control character) never matches as a whole, even though the clean
    part of it is genuinely present on the page.
    """
    words = text.split(" ")
    variants = []
    for cut in range(len(words) - 1, 0, -1):
        candidate = " ".join(words[:cut])
        if len(candidate) < min_len:
            break
        variants.append(candidate)
    return variants


def _split_at_symbols(text: str, min_len: int = 20) -> list[str]:
    """Splits at recovered Symbol-font characters, longest fragment first.

    Ingestion resolves Greek letters and math operators that the PDF's own
    text layer still stores as unmapped control characters (see
    services/symbol_text.py). A cited passage therefore reads "αcc fck / γC"
    while the page itself reads "\\x06cc fck / \\x03C", and searching for the
    former finds nothing. The text between those characters is unaffected and
    still matches verbatim, so a formula-bearing passage stays locatable.
    """
    fragments = []
    current = []
    for char in text:
        if char in _SYMBOL_CHARS:
            fragments.append("".join(current))
            current = []
        else:
            current.append(char)
    fragments.append("".join(current))
    return sorted(
        (f.strip() for f in fragments if len(f.strip()) >= min_len),
        key=len,
        reverse=True,
    )


def _search_snippets(text: str, max_len: int = 80) -> list[str]:
    """Candidate strings to search for, most-specific first.

    The cited chunk text may include a prepended clause heading (added for
    retrieval quality) that isn't literally at that spot on the page, and
    may wrap differently than the PDF's own line breaks — so a single exact
    match on the full text isn't reliable. Falls back to individual lines.
    """
    normalized = " ".join(text.split())
    candidates = []
    if len(normalized) > max_len:
        candidates.append(normalized[:max_len])
    candidates.append(normalized)
    candidates.extend(_shrink_from_end(normalized))
    for line in text.split("\n"):
        line = line.strip()
        if len(line) > 15:
            candidates.append(line[:max_len])
            candidates.extend(_shrink_from_end(line))
    # Last resort: every candidate above fails outright if the passage
    # contains a recovered symbol, so retry on the parts around it.
    candidates.extend(_split_at_symbols(normalized))
    return candidates


def build_highlighted_copy(source_path: Path, page_number: int, highlight_text: str) -> Path:
    """Returns a path to a temp copy of source_path with the cited passage
    highlighted on page_number (1-indexed), caching by content so repeat
    requests for the same citation reuse the same file. Never modifies the
    original document. Falls back to a plain (unhighlighted) copy of that
    page's content if no snippet of highlight_text can be located.
    """
    cache_key = hashlib.sha1(
        f"{source_path}:{page_number}:{highlight_text}".encode("utf-8")
    ).hexdigest()
    cached = _CACHE_DIR / f"{cache_key}.pdf"
    if cached.exists():
        return cached

    doc = fitz.open(source_path)
    try:
        if not (1 <= page_number <= doc.page_count):
            doc.save(cached)
            return cached

        page = doc[page_number - 1]
        if highlight_text:
            for snippet in _search_snippets(highlight_text):
                rects = page.search_for(snippet)
                if rects:
                    for rect in rects:
                        page.add_highlight_annot(rect)
                    break

        doc.save(cached)
    finally:
        doc.close()

    return cached
