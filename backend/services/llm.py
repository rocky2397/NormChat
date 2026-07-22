import difflib
import re

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config import settings
from models.chat import ChatResponse, SourceChunk
from services.embeddings import get_embeddings
from services.reranking import bm25_rank_ids, reciprocal_rank_fusion, rerank_ids
from services.storage import get_collection

SYSTEM_PROMPT = """Du bist ein technischer Assistent für Bauingenieure und Architekten in der DACH-Region.
Beantworte Fragen ausschließlich auf Basis des bereitgestellten Kontexts aus Normdokumenten.

Regeln:
- Verwende kein Allgemeinwissen. Nur der Kontext zählt.
- Wenn der Kontext keine klare Antwort enthält, sage das ausdrücklich.
- Verweise immer auf die konkrete Klausel oder Abschnittsnummer, falls im Kontext vorhanden.
- Wenn du dich auf eine Quelle beziehst, nenne die Norm-Bezeichnung oder den
  Dokumentnamen (z. B. "DIN 4102-2"), niemals die interne Markierung
  "[Quelle N]" aus dem Kontext — diese ist nur zur internen Zuordnung gedacht
  und wird dem Nutzer nicht angezeigt.
- Halte die Antwort präzise und technisch. Der Nutzer ist Fachingenieur.
- Antworte auf Deutsch, sofern die Frage auf Deutsch gestellt wird.
- Schreibe Formeln immer in LaTeX, eingeschlossen in \\( ... \\) für Inline-Formeln
  oder \\[ ... \\] für abgesetzte Formeln (z. B. \\( f_{cd} = \\alpha_{cc} \\cdot f_{ck} / \\gamma_c \\))."""


def _format_context(sources: list[SourceChunk]) -> str:
    blocks = []
    for i, source in enumerate(sources, start=1):
        ref = source.norm_reference or source.filename
        if source.edition:
            ref = f"{ref} ({source.edition})"
        blocks.append(
            f"[Quelle {i}] {ref}, Seite {source.page_number}:\n{source.chunk_text}"
        )
    return "\n\n".join(blocks)


_CITATION_LABEL_PATTERN = re.compile(r"\[Quelle (\d+)\]")


def _replace_citation_labels(answer: str, sources: list[SourceChunk]) -> str:
    """The model is instructed to cite documents by name, but LLM output is
    non-deterministic — this is a deterministic backstop that rewrites any
    "[Quelle N]" label it emits anyway into the matching document's name, so
    the internal indexing scheme never leaks into the user-visible answer.
    """

    def repl(match: re.Match) -> str:
        index = int(match.group(1))
        if 1 <= index <= len(sources):
            source = sources[index - 1]
            return source.norm_reference or source.filename
        return match.group(0)

    return _CITATION_LABEL_PATTERN.sub(repl, answer)


def retrieve_sources(project_id: str, question: str) -> list[SourceChunk]:
    collection = get_collection(project_id)
    total = collection.count()
    if total == 0:
        return []
    pool_size = min(settings.retrieval_candidate_pool, total)

    embeddings = get_embeddings()
    query_vector = embeddings.embed_query(question)
    vector_results = collection.query(
        query_embeddings=[query_vector],
        n_results=pool_size,
        include=["documents", "metadatas"],
    )
    vector_ids = vector_results["ids"][0]

    # BM25 needs the full corpus for term-frequency stats; catches chunks
    # that share the question's exact terminology but rank low on pure
    # embedding similarity.
    all_chunks = collection.get(include=["documents", "metadatas"])
    all_ids = all_chunks["ids"]
    id_to_doc = dict(zip(all_ids, all_chunks["documents"]))
    id_to_meta = dict(zip(all_ids, all_chunks["metadatas"]))
    bm25_ids = bm25_rank_ids(question, all_ids, all_chunks["documents"])[:pool_size]

    fused_ids = reciprocal_rank_fusion(vector_ids, bm25_ids)[:pool_size]
    fused_docs = [id_to_doc[cid] for cid in fused_ids]
    final_ids = rerank_ids(question, fused_ids, fused_docs, settings.top_k_chunks)

    sources: list[SourceChunk] = []
    for cid in final_ids:
        meta = id_to_meta[cid]
        sources.append(
            SourceChunk(
                document_id=meta["document_id"],
                filename=meta["source_filename"],
                page_number=int(meta["page_number"]),
                chunk_text=id_to_doc[cid],
                norm_reference=meta.get("norm_reference") or None,
                edition=meta.get("edition") or None,
            )
        )
    return sources


def generate_answer(question: str, sources: list[SourceChunk]) -> str:
    if not sources:
        return (
            "Im hochgeladenen Dokumentenbestand dieses Projekts konnte keine "
            "relevante Passage gefunden werden."
        )

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    context = _format_context(sources)
    llm = ChatOpenAI(
        model=settings.openai_model,
        openai_api_key=settings.openai_api_key,
        temperature=0,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Kontext:\n{context}\n\n"
                f"Frage: {question}\n\n"
                "Beantworte die Frage basierend ausschließlich auf dem Kontext."
            ),
        },
    ]
    response = llm.invoke(messages)
    return response.content.strip()


class _SourceExcerpt(BaseModel):
    source_index: int = Field(description="1-based [Quelle N] number this excerpt belongs to")
    excerpt: str = Field(
        description="The exact, verbatim, character-for-character substring copied "
        "from that source's text that the answer actually relied on — a short "
        "phrase or single sentence, not a paraphrase and not the whole passage."
    )


class _CitationExcerpts(BaseModel):
    excerpts: list[_SourceExcerpt] = Field(
        description="One entry per source that genuinely contributed to the answer. "
        "Omit sources that were only tangentially retrieved and not actually used."
    )


def extract_citation_excerpts(
    question: str, answer: str, sources: list[SourceChunk]
) -> dict[int, str]:
    """Asks the model which exact excerpt it relied on per source, for precise
    PDF highlighting. Isolated from generate_answer() on purpose: this is a
    locate-existing-text hint, not an assertion of fact, so if the model
    misquotes or this call fails outright, downstream search-on-page simply
    won't find it and we fall back to the raw chunk_text — it never affects
    the actual answer shown to the user.
    """
    if not sources or not settings.openai_api_key:
        return {}

    context = _format_context(sources)
    llm = ChatOpenAI(
        model=settings.openai_model,
        openai_api_key=settings.openai_api_key,
        temperature=0,
    )
    structured_llm = llm.with_structured_output(_CitationExcerpts)

    prompt = (
        f"Frage: {question}\n\n"
        f"Antwort: {answer}\n\n"
        f"Kontext (nummerierte Quellen):\n{context}\n\n"
        "Gib für jede Quelle, die tatsächlich zur obigen Antwort beigetragen hat, "
        "das exakte, wortwörtliche Zitat aus dem jeweiligen Quellentext zurück, auf "
        "das sich die Antwort stützt. Das Zitat muss zeichengenau im Quellentext "
        "vorkommen (keine Paraphrase) und kurz sein (ein Satz oder eine Kernaussage, "
        "nicht der ganze Abschnitt). Quellen ohne tatsächlichen Beitrag weglassen."
    )

    try:
        result = structured_llm.invoke(prompt)
    except Exception:
        return {}

    return {e.source_index: e.excerpt for e in result.excerpts}


def _sliding_windows(chunk_text: str, max_lines: int = 3) -> list[str]:
    raw_lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
    windows = []
    for size in range(1, max_lines + 1):
        for start in range(len(raw_lines) - size + 1):
            windows.append(" ".join(raw_lines[start : start + size]))
    return windows


def _ground_excerpt(excerpt: str, chunk_text: str, threshold: float = 0.35) -> str | None:
    """Despite instructions, the model tends to paraphrase/clean up its quoted
    excerpt rather than copy it character-for-character (confirmed in
    testing — PyMuPDF's on-page search then finds nothing). This finds the
    closest REAL span of chunk_text — a window of 1-3 consecutive raw PDF
    lines, since the target sentence is often split across several by the
    page's own line wrapping — so what actually gets searched for is
    guaranteed to be text that exists verbatim in the source.
    """
    if not excerpt:
        return None
    candidates = _sliding_windows(chunk_text)
    if not candidates:
        return None
    best_score, best_candidate = max(
        (difflib.SequenceMatcher(None, excerpt, c).ratio(), c) for c in candidates
    )
    return best_candidate if best_score >= threshold else None


def chat(project_id: str, question: str) -> ChatResponse:
    sources = retrieve_sources(project_id, question)
    answer = generate_answer(question, sources)
    excerpts = extract_citation_excerpts(question, answer, sources)
    for i, source in enumerate(sources, start=1):
        raw_excerpt = excerpts.get(i)
        source.highlight_snippet = (
            _ground_excerpt(raw_excerpt, source.chunk_text) if raw_excerpt else None
        )
    answer = _replace_citation_labels(answer, sources)
    return ChatResponse(answer=answer, sources=sources)
