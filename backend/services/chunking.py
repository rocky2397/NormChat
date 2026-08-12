import re
from collections import Counter
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from services.symbol_text import build_symbol_maps, extract_page_text
from services.tables import TableBlock, extract_tables, split_table_rows

_DIGIT_RUN = re.compile(r"\d+")
BOILERPLATE_FREQUENCY_THRESHOLD = 0.6
BOILERPLATE_MIN_PAGES = 3


CLAUSE_PATTERN = re.compile(
    r"(?:^|\n)(\d+(?:\.\d+)+)\s+",
    re.MULTILINE,
)


@dataclass
class PageText:
    page_number: int
    text: str
    # Grids on this page, serialised separately. The flattened copy is still
    # in `text`: excluding it would mean rewriting extract_page_text(), which
    # deliberately reproduces get_text() byte-for-byte because boilerplate
    # detection depends on that layout.
    tables: list[TableBlock] = field(default_factory=list)


@dataclass
class TextChunk:
    text: str
    page_number: int
    chunk_index: int
    norm_reference: str | None


def extract_pages(pdf_path: str) -> list[PageText]:
    pages: list[PageText] = []
    with fitz.open(pdf_path) as pdf:
        # Built once per document: the Symbol subsets are shared across pages,
        # and resolving them page by page would re-parse the same font objects.
        symbol_maps = build_symbol_maps(pdf)
        for index, page in enumerate(pdf, start=1):
            text = extract_page_text(page, symbol_maps)
            pages.append(
                PageText(
                    page_number=index,
                    text=text.strip(),
                    tables=extract_tables(page, index),
                )
            )
    return pages


EDGE_LINES = 2


def _normalize_line(line: str) -> str:
    # Collapses digit runs so a header/footer that only varies by page
    # number (or a similar counter) still matches across pages.
    return _DIGIT_RUN.sub("#", line.strip())


def _edge_line_indices(num_lines: int) -> set[int]:
    # Headers/footers live at the physical top/bottom of a page; restricting
    # detection to these edges (rather than the whole page) keeps mid-page
    # content — e.g. an isolated numerator in a stacked formula layout —
    # from ever being mistaken for a repeating page number.
    indices = set(range(min(EDGE_LINES, num_lines)))
    indices |= set(range(max(0, num_lines - EDGE_LINES), num_lines))
    return indices


def strip_boilerplate(
    pages: list[PageText], norm_reference: str | None = None
) -> tuple[list[PageText], str | None]:
    """Remove lines repeated near-identically across most pages' top/bottom
    edges (running headers, edition stamps, page-number footers) before
    chunking.

    A line that instead varies per page (e.g. a running section title) has a
    different normalized form on each page and is left alone — repetition
    frequency is the signal, not position on the page.
    """
    if len(pages) < BOILERPLATE_MIN_PAGES:
        return pages, None

    page_lines = [page.text.split("\n") for page in pages]

    normalized_counts: Counter[str] = Counter()
    raw_variants: dict[str, Counter[str]] = {}
    for lines in page_lines:
        seen_this_page = set()
        for i in _edge_line_indices(len(lines)):
            norm = _normalize_line(lines[i])
            if not norm or norm in seen_this_page:
                continue
            seen_this_page.add(norm)
            normalized_counts[norm] += 1
            raw_variants.setdefault(norm, Counter())[lines[i].strip()] += 1

    threshold = max(BOILERPLATE_MIN_PAGES, int(len(pages) * BOILERPLATE_FREQUENCY_THRESHOLD))
    boilerplate_norms = {norm for norm, count in normalized_counts.items() if count >= threshold}

    edition: str | None = None
    descriptive_norms = [n for n in boilerplate_norms if any(ch.isalpha() for ch in n)]
    if descriptive_norms:
        # A repeating line that actually names this document (contains the
        # already-identified norm reference, e.g. "EN 1992-1-1") is the
        # edition stamp; other repeating lines are more likely to be
        # unrelated boilerplate (library stamps, scan-session markers) —
        # which tend to run longer, so prefer the shortest as a fallback.
        matching = [
            n for n in descriptive_norms
            if norm_reference and norm_reference.lower() in raw_variants[n].most_common(1)[0][0].lower()
        ]
        best_norm = min(matching or descriptive_norms, key=len)
        edition = raw_variants[best_norm].most_common(1)[0][0]

    cleaned_pages = []
    for page, lines in zip(pages, page_lines):
        edge_idx = _edge_line_indices(len(lines))
        kept = [
            line
            for i, line in enumerate(lines)
            if not (i in edge_idx and _normalize_line(line) in boilerplate_norms)
        ]
        cleaned_pages.append(
            PageText(
                page_number=page.page_number,
                text="\n".join(kept).strip(),
                tables=page.tables,
            )
        )
    return cleaned_pages, edition


# A contents line ends in dot leaders and a page number; a cover carries
# publisher boilerplate.
_TOC_LEADER = re.compile(r"\.{4,}\s*\d+\s*$")
_COVER_MARKER = re.compile(r"Medieninhaber|Copyright ©|DEUTSCHE NORM|Alle Rechte vorbehalten")
TOC_LINE_SHARE = 0.3


def _is_contents_page(text: str) -> bool:
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) < 5:
        return False
    leaders = sum(1 for line in lines if _TOC_LEADER.search(line))
    return leaders / len(lines) >= TOC_LINE_SHARE


def strip_front_matter(pages: list[PageText]) -> list[PageText]:
    """Blanks cover and table-of-contents pages before chunking.

    Measured motivation (eval/runs/2026-08-06-baseline.md): a contents page
    repeats every clause number in the document and a cover is publisher
    boilerplate, so both match a question about national supplements without
    carrying any rule of their own. They outranked the operative clauses.

    Forewords are deliberately **kept**, having been tried and reverted. They
    look like the same kind of noise, but they are where a document states
    its relationship to others — "Die ÖNORM EN 1995-1-2 und ÖNORM B 1995-1-2
    sind gemeinsam anzuwenden". Removing them made the model substitute an
    invented explanation ("die konsolidierte Fassung von …") for a question
    about which norms apply.

    Pages are blanked rather than removed so page numbers, which every
    citation depends on, keep pointing at the same physical page.
    """
    cleaned: list[PageText] = []
    for page in pages:
        text = page.text
        if (page.page_number == 1 and _COVER_MARKER.search(text)) or _is_contents_page(text):
            text = ""
        # A blanked page loses its tables too: a contents page lists table
        # captions, and keeping its grids would reintroduce exactly the noise
        # this pass removes.
        cleaned.append(
            PageText(
                page_number=page.page_number,
                text=text,
                tables=page.tables if text else [],
            )
        )
    return cleaned


def _split_on_clauses(
    text: str, carried_heading: str
) -> tuple[list[tuple[str, str]], str]:
    """Splits a page's text at clause-number boundaries (e.g. "6.2.2 ...").

    Clauses routinely span multiple pages in these documents, so text
    before a page's first match (or an entire page with no match) belongs
    to whichever clause was still open from a previous page — carried_heading
    tracks that across the whole document, not just within one page.
    Returns (list of (heading, segment_text)), updated carried_heading).
    """
    matches = list(CLAUSE_PATTERN.finditer(text))
    if not matches:
        return [(carried_heading, text)], carried_heading

    segments: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        leading = text[: matches[0].start()].strip()
        if leading:
            segments.append((carried_heading, leading))

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[start:end].strip()
        if segment:
            carried_heading = segment.split("\n", 1)[0].strip()
            segments.append((carried_heading, segment))

    return segments, carried_heading


def _token_splitter() -> RecursiveCharacterTextSplitter:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:
        encoding = None

    def length_fn(text: str) -> int:
        if encoding:
            return len(encoding.encode(text))
        return len(text.split())

    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=length_fn,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _fits(splitter: RecursiveCharacterTextSplitter):
    """Whether a piece is within the configured chunk budget.

    Borrows the splitter's own length function so tables are measured the
    same way prose is, rather than by a second, drifting definition.
    """
    length = splitter._length_function

    def check(text: str) -> bool:
        return length(text) <= settings.chunk_size

    return check


def chunk_pages(pages: list[PageText], norm_reference: str | None) -> list[TextChunk]:
    splitter = _token_splitter()
    chunks: list[TextChunk] = []
    chunk_index = 0
    carried_heading = ""

    for page in pages:
        # Tables are emitted whole rather than fed through the token
        # splitter, which would cut a grid mid-row and destroy the column
        # alignment the serialisation exists to preserve. Oversized ones are
        # split by rows with the header repeated, so each piece stays
        # readable on its own.
        for table in page.tables:
            for piece in split_table_rows(table.text, _fits(splitter)):
                chunks.append(
                    TextChunk(
                        text=piece,
                        page_number=table.page_number,
                        chunk_index=chunk_index,
                        norm_reference=norm_reference,
                    )
                )
                chunk_index += 1

        if not page.text:
            continue

        segments, carried_heading = _split_on_clauses(page.text, carried_heading)

        for heading, segment in segments:
            for piece in splitter.split_text(segment):
                piece = piece.strip()
                if not piece:
                    continue
                # A clause spanning multiple split pieces (or multiple
                # pages) loses its own heading on every piece but the
                # first — re-attach it (it's real text from this clause's
                # own first line, not invented) so every piece stays
                # identifiable by clause number.
                if heading and not piece.startswith(heading):
                    piece = f"{heading}\n{piece}"
                chunks.append(
                    TextChunk(
                        text=piece,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        norm_reference=norm_reference,
                    )
                )
                chunk_index += 1

    return chunks
