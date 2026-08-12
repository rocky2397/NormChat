"""Table extraction as structured chunks.

Plain text extraction returns table cells in reading order, so row
membership survives only as sequence. Asked for the minimum concrete cover
in exposure class XC4, the tool read 15 mm — the S1 row of Tabelle 4.4N —
while the question concerned S4, whose value is 30 mm, and then cited a
table that does not exist in the document. Prose failures announce
themselves; a flattened grid is legible enough to be misread.

Serialising to Markdown keeps row and column association intact through
embedding, reranking and the answering context. The cell values are real
page text, so a serialised table can still be quoted and highlighted.
"""

import re
from dataclasses import dataclass

import fitz  # PyMuPDF

from services.symbol_text import _RESIDUAL_CONTROL

# Norm tables are captioned "Tabelle 4.4N — Mindestbetondeckung …".
# Detection alone is not selective enough: on ÖNORM EN 1992-1-1 find_tables()
# reports 87 pages while only 32 carry a caption, the rest being multi-column
# prose and header blocks read as grids. Requiring a caption turns ~97%
# recall and ~36% precision into something usable, at the cost of the single
# uncaptioned table in that document.
CAPTION_PATTERN = re.compile(r"Tabelle\s+[A-Z]?\.?\d+(?:\.\d+)*[A-Z]*")

MIN_ROWS = 2
MIN_COLUMNS = 2


@dataclass
class TableBlock:
    page_number: int
    caption: str | None
    markdown: str

    @property
    def text(self) -> str:
        """Caption first, so the chunk names the table it came from.

        Mirrors the clause heading the chunker re-attaches to every piece:
        a grid with no caption is far harder to place once retrieved.
        """
        return f"{self.caption}\n{self.markdown}" if self.caption else self.markdown


def _clean_cell(value: str | None) -> str:
    """Cell text as one line, with unresolved symbol glyphs removed.

    find_tables() does its own extraction, so it never passes through
    services/symbol_text.py — cells arrive carrying the same control
    characters that Greek letters degrade to. Newlines inside a cell would
    break the pipe row, so they collapse to spaces.
    """
    if value is None:
        return ""
    cleaned = _RESIDUAL_CONTROL.sub("", value)
    # Escape pipes so a cell containing one cannot fabricate a column.
    return " ".join(cleaned.split()).replace("|", "\\|")


def _is_degenerate(rows: list[list[str]]) -> bool:
    if len(rows) < MIN_ROWS or max((len(r) for r in rows), default=0) < MIN_COLUMNS:
        return True
    return not any(cell for row in rows for cell in row)


# How many leading rows to consider when looking for the real column labels.
HEADER_SEARCH_DEPTH = 3


def _header_index(rows: list[list[str]]) -> int:
    """Which leading row actually carries the column labels.

    Norm tables stack a merged title and a spanning group label above the
    real header, so the first row is often "Dauerhaftigkeitsanforderung für
    cmin,dur (mm)" with seven empty cells after it. Treating that as the
    header puts the exposure classes in what reads as a data row — the tool
    then answered 25 mm for XC4, which is the XC2/XC3 column, having
    miscounted from a header that was not one. The real header is the most
    populated of the leading rows.
    """
    depth = max(1, min(HEADER_SEARCH_DEPTH, len(rows) - 1))
    filled = [sum(1 for cell in row if cell) for row in rows[:depth]]
    return filled.index(max(filled))


def _merge_header(preceding: list[list[str]], header: list[str]) -> list[str]:
    """Fills empty header cells from the spanning rows above them.

    The label for the first column usually lives in the spanning row
    ("Anforderungsklasse"), leaving the header's own first cell blank.
    """
    merged = list(header)
    for i, cell in enumerate(merged):
        if cell:
            continue
        for row in reversed(preceding):
            if i < len(row) and row[i]:
                merged[i] = row[i]
                break
    return merged


def _to_markdown(rows: list[list[str]]) -> str:
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]

    index = _header_index(padded)
    preceding, header, body = padded[:index], padded[index], padded[index + 1 :]

    # Rows above the header are titles, not data: emitted as plain lines so
    # they stay searchable without occupying a column position.
    lines = [" ".join(cell for cell in row if cell) for row in preceding if any(row)]
    merged = _merge_header(preceding, header)
    lines += [
        "| " + " | ".join(merged) + " |",
        "| " + " | ".join("---" for _ in merged) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def _captions_by_position(page: fitz.Page) -> list[tuple[float, str]]:
    """(bottom y, caption text) for every caption block on the page."""
    found: list[tuple[float, str]] = []
    for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
        flat = " ".join(_RESIDUAL_CONTROL.sub("", text).split())
        if CAPTION_PATTERN.search(flat):
            found.append((y1, flat))
    return found


def _caption_for(table_top: float, captions: list[tuple[float, str]]) -> str | None:
    """The nearest caption above this table.

    Pages carry more than one table — Tabelle 4.3N and 4.4N share a page —
    so the caption cannot simply be the first one found, or every grid on
    the page would be labelled with the same name.
    """
    above = [(y, text) for y, text in captions if y <= table_top]
    return max(above, key=lambda pair: pair[0])[1] if above else None


def extract_tables(page: fitz.Page, page_number: int) -> list[TableBlock]:
    """Captioned grids on this page, serialised to Markdown."""
    try:
        found = page.find_tables()
    except Exception:
        # Layout analysis is best-effort; a page it cannot parse must not
        # fail the ingestion of an otherwise readable document.
        return []

    captions = _captions_by_position(page)
    if not captions:
        return []

    blocks: list[TableBlock] = []
    for table in found.tables:
        rows = [[_clean_cell(cell) for cell in row] for row in table.extract()]
        if _is_degenerate(rows):
            continue
        blocks.append(
            TableBlock(
                page_number=page_number,
                caption=_caption_for(table.bbox[1], captions),
                markdown=_to_markdown(rows),
            )
        )
    return blocks


def split_table_rows(text: str, fits) -> list[str]:
    """Splits an oversized table by rows, repeating the header on each piece.

    A grid cut mid-row loses the column alignment the serialisation exists
    to preserve, and a piece without its header is a wall of numbers nobody
    can place. Both are avoided by cutting only between rows and carrying
    the caption and header across.
    """
    if fits(text):
        return [text]

    lines = text.split("\n")
    separator = next((i for i, line in enumerate(lines) if set(line) <= set("| -")), None)
    if separator is None or separator + 1 >= len(lines):
        # Not a shape we can split safely; better one oversized chunk than a
        # silently mangled one.
        return [text]

    header, body = lines[: separator + 1], lines[separator + 1 :]
    pieces: list[str] = []
    current: list[str] = []
    for row in body:
        candidate = "\n".join(header + current + [row])
        if current and not fits(candidate):
            pieces.append("\n".join(header + current))
            current = [row]
        else:
            current.append(row)
    if current:
        pieces.append("\n".join(header + current))
    return pieces
