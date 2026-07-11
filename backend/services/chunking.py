import re
from dataclasses import dataclass

import pdfplumber
import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings


CLAUSE_PATTERN = re.compile(
    r"(?:^|\n)(\d+(?:\.\d+)+)\s+",
    re.MULTILINE,
)


@dataclass
class PageText:
    page_number: int
    text: str


@dataclass
class TextChunk:
    text: str
    page_number: int
    chunk_index: int
    norm_reference: str | None


def extract_pages(pdf_path: str) -> list[PageText]:
    pages: list[PageText] = []
    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append(PageText(page_number=index, text=text.strip()))
    return pages


def _split_on_clauses(text: str) -> list[str]:
    matches = list(CLAUSE_PATTERN.finditer(text))
    if len(matches) < 2:
        return []

    segments: list[str] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[start:end].strip()
        if segment:
            segments.append(segment)
    return segments


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


def chunk_pages(pages: list[PageText], norm_reference: str | None) -> list[TextChunk]:
    splitter = _token_splitter()
    chunks: list[TextChunk] = []
    chunk_index = 0

    for page in pages:
        if not page.text:
            continue

        clause_segments = _split_on_clauses(page.text)
        segments = clause_segments if clause_segments else [page.text]

        for segment in segments:
            for piece in splitter.split_text(segment):
                piece = piece.strip()
                if not piece:
                    continue
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
