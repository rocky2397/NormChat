import hashlib
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

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
