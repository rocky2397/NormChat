import difflib
import re
from dataclasses import dataclass, field

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
- Wenn sich Angaben aus verschiedenen Teilen derselben Normenreihe
  unterscheiden (z. B. EN 1992-1-1 gegenüber EN 1992-2), wähle nicht
  stillschweigend einen Wert aus. Nenne beide Werte, ordne jeden ausdrücklich
  seinem Teil zu und gib an, für welchen Anwendungsbereich der jeweilige Teil
  laut Kontext gilt. Wenn der Kontext den Anwendungsbereich nicht hergibt,
  sage das und überlasse die Entscheidung dem Fachingenieur.
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


# A label is "Quelle"/"Quellen" followed by one or more indices, which the
# model writes in several shapes — bracketed as instructed ("[Quelle 1]"), but
# also parenthesised prose ("(siehe Quelle 1 und 2)") and bare ("Quelle 3").
# The bracketed form is consumed whole; the others keep their surrounding
# words so the sentence still reads.
_INDEX_LIST = r"\d+(?:\s*(?:,|und|and|&|bis)\s*\d+)*"
_BRACKETED_LABEL = re.compile(rf"\[\s*Quellen?\s+(?P<indices>{_INDEX_LIST})\s*\]")
_BARE_LABEL = re.compile(rf"\bQuellen?\s+(?P<indices>{_INDEX_LIST})")


def _replace_citation_labels(answer: str, sources: list[SourceChunk]) -> str:
    """The model is instructed to cite documents by name, but LLM output is
    non-deterministic — this is a deterministic backstop that rewrites any
    source label it emits anyway into the matching document's name, so the
    internal indexing scheme never leaks into the user-visible answer.

    Matching only "[Quelle N]" was not enough: an eval run produced
    "(siehe Quelle 1 und 2)", which reached the user untouched.
    """

    def _named(match: re.Match) -> str:
        index = int(match.group(0))
        if 1 <= index <= len(sources):
            source = sources[index - 1]
            return source.norm_reference or source.filename
        return match.group(0)

    def _rewrite(match: re.Match) -> str:
        indices = match.group("indices")
        # Substituting inside the index list preserves the model's own
        # separators, so "1 und 2" and "1, 2, 3" keep reading naturally.
        named = re.sub(r"\d+", _named, indices)
        if named == indices:
            # Nothing resolved (every index out of range) — leave the label
            # exactly as it was rather than mangling it into bare numbers.
            return match.group(0)
        return named

    answer = _BRACKETED_LABEL.sub(_rewrite, answer)
    return _BARE_LABEL.sub(_rewrite, answer)


# A national annex states its rules as a delta against the European norm,
# addressing the parent clause by number: "Festlegung zu ÖNORM EN 1992-1-1,
# Abschnitt 3.1.6(1)P — Der empfohlene Wert wird übernommen." Such a chunk
# carries almost no domain vocabulary, so neither the embedding nor BM25 can
# reach it from a question phrased in words, and three of five reference
# questions missed the clause that actually decided the answer
# (eval/runs/2026-08-06-front-matter-and-labels.md). The clause number is the
# one token it does share, so it is looked up literally.
_CLAUSE_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)+)")
CLAUSE_LOOKUP_LIMIT = 3


def _leading_clause_numbers(texts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(clause number, owning document id) for what the first pass landed on.

    Reads the heading the chunker prepends to every piece of a clause, so a
    chunk from the middle of §6.2 still reports 6.2. The owning document
    travels with the number because the lookup must exclude that document
    and only that one.
    """
    seen: list[tuple[str, str]] = []
    numbers: set[str] = set()
    for text, document_id in texts:
        match = _CLAUSE_HEADING.match(text)
        if match and match.group(1) not in numbers:
            numbers.add(match.group(1))
            seen.append((match.group(1), document_id))
    return seen


_NORM_PART = re.compile(r"\b(\d{4}(?:-\d+)*)\b")


def _norm_part(norm_reference: str | None) -> str | None:
    """The part number a document belongs to — 1992-1-1, or 1992-2.

    A European norm and its national annex share a part (EN 1992-1-1 and
    B 1992-1-1 are both 1992-1-1); different parts of the same family are
    different documents about different things.
    """
    match = _NORM_PART.search(norm_reference or "")
    return match.group(1) if match else None


def _parts_in_conflict(sources: list[SourceChunk]) -> dict[str, list[str]]:
    """Norm families for which more than one part was retrieved.

    Different parts of one Eurocode legitimately give different values for
    the same symbol — EN 1992-1-1 recommends α_cc = 1,0 for buildings while
    EN 1992-2 recommends 0,85 for bridges. With both in context and nothing
    saying which governs, the answer flipped between runs on context ordering
    alone (eval/runs/2026-08-06-compound-expansion.md). Detected here so the
    model is told to attribute and contrast rather than quietly pick one.
    """
    by_family: dict[str, set[str]] = {}
    for source in sources:
        family = _norm_family(source.norm_reference)
        part = _norm_part(source.norm_reference)
        if family and part:
            by_family.setdefault(family, set()).add(part)
    return {f: sorted(parts) for f, parts in by_family.items() if len(parts) > 1}


_NORM_FAMILY = re.compile(r"\b(\d{4})\b")


def _norm_family(norm_reference: str | None) -> str | None:
    """The Eurocode number a document belongs to — 1992 for EN and B 1992-1-1.

    Clause numbers only mean anything inside one family. Without this scope,
    looking up EN 1992-1-1 §9.2.2 (Querkraftbewehrung) also matched
    ÖNORM B 1991-1-3 §9.2.2 (Schneeverwehungen), putting a snow-load clause
    into a shear question.
    """
    match = _NORM_FAMILY.search(norm_reference or "")
    return match.group(1) if match else None


def _clause_reference_ids(
    clause: str,
    exclude_document_ids: set[str],
    ids: list[str],
    id_to_doc: dict[str, str],
    id_to_meta: dict[str, dict],
    family: str | None = None,
) -> list[str]:
    """Chunks in *other* documents that cite this clause by number.

    Only the document the clause itself came from is excluded — a norm cites
    its own clauses constantly, so including it would just return more of the
    same passage. Excluding every document already present in the results
    instead is too coarse: a single front-matter chunk of ÖNORM B 1992-1-1
    ranking in the first pass would then bar its §6.1.4 from the second,
    which is the exact clause the lookup exists to reach.
    """
    # Bounded on both sides so 3.1.6 does not match inside 13.1.6 or 3.1.60,
    # while still matching the "3.1.6(1)P" form the annexes use.
    pattern = re.compile(rf"(?<![\d.]){re.escape(clause)}(?![\d])")
    return [
        cid
        for cid in ids
        if id_to_meta[cid]["document_id"] not in exclude_document_ids
        and (family is None or _norm_family(id_to_meta[cid].get("norm_reference")) == family)
        and pattern.search(id_to_doc[cid])
    ]


@dataclass
class RetrievalTrace:
    """Where every chunk id ranked at each stage of one retrieve_sources()
    call, in pipeline order: dense -> lexical -> fused -> reranked -> final.

    Filled in only when a caller passes an instance in. Recording is
    write-only — it must never influence the ranking itself; a test asserts
    the sources are identical with and without a trace attached. Exists for
    backend/eval/retrieval_probe.py, which reports where the gold chunks
    rank at each stage.
    """

    vector_ids: list[str] = field(default_factory=list)
    bm25_ids: list[str] = field(default_factory=list)
    fused_ids: list[str] = field(default_factory=list)
    reranked_ids: list[str] = field(default_factory=list)
    final_ids: list[str] = field(default_factory=list)
    # Metadata for every chunk id in the collection, so a consumer can map
    # any ranked id to (norm_reference, page_number) without re-querying.
    id_to_meta: dict[str, dict] = field(default_factory=dict)


def retrieve_sources(
    project_id: str, question: str, trace: RetrievalTrace | None = None
) -> list[SourceChunk]:
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

    if trace is not None:
        trace.vector_ids = list(vector_ids)
        trace.bm25_ids = list(bm25_ids)
        trace.fused_ids = list(fused_ids)
        # Snapshot before the clause-lookup pass mutates final_ids.
        trace.reranked_ids = list(final_ids)
        trace.id_to_meta = dict(id_to_meta)

    # Second pass: whatever clauses the first pass landed on, pull in the
    # places other documents modify them. Appended rather than substituted —
    # this adds the national deviation to the rule, it does not replace it.
    already = set(final_ids)
    retrieved = [(id_to_doc[cid], id_to_meta[cid]["document_id"]) for cid in final_ids]
    owner_family = {
        id_to_meta[cid]["document_id"]: _norm_family(id_to_meta[cid].get("norm_reference"))
        for cid in final_ids
    }
    for clause, owner_id in _leading_clause_numbers(retrieved):
        for cid in _clause_reference_ids(
            clause, {owner_id}, all_ids, id_to_doc, id_to_meta, owner_family.get(owner_id)
        ):
            if cid not in already:
                already.add(cid)
                final_ids.append(cid)
                break  # one modifying clause per parent clause is enough
        if len(final_ids) >= settings.top_k_chunks + CLAUSE_LOOKUP_LIMIT:
            break

    if trace is not None:
        trace.final_ids = list(final_ids)

    sources: list[SourceChunk] = []
    for cid in final_ids:
        meta = id_to_meta[cid]
        sources.append(
            SourceChunk(
                document_id=meta["document_id"],
                filename=meta["source_filename"],
                page_number=int(meta["page_number"]),
                # The indexed text may carry appended parent-clause headings
                # (services/reference_resolution.py); everything user-facing —
                # display, LLM context, excerpt grounding — must see only text
                # that exists on the cited page, so the original is read back
                # from raw_text. Collections indexed before enrichment existed
                # carry no raw_text; their stored text is already original.
                chunk_text=meta.get("raw_text") or id_to_doc[cid],
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

    # The system rule alone is easy for the model to overlook when the parts
    # sit many chunks apart, so the specific collision is named here too.
    conflicts = _parts_in_conflict(sources)
    warning = ""
    if conflicts:
        listed = "; ".join(
            f"Normenreihe {family}: Teile {', '.join(parts)}"
            for family, parts in sorted(conflicts.items())
        )
        warning = (
            f"\n\nAchtung: Der Kontext enthält mehrere Teile derselben Normenreihe "
            f"({listed}). Falls sich deren Angaben unterscheiden, nenne beide, ordne "
            f"jede Angabe ihrem Teil zu und gib den jeweiligen Anwendungsbereich an, "
            f"statt einen Wert auszuwählen."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Kontext:\n{context}\n\n"
                f"Frage: {question}\n\n"
                "Beantworte die Frage basierend ausschließlich auf dem Kontext."
                f"{warning}"
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
