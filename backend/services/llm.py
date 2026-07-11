from langchain_openai import ChatOpenAI

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
- Halte die Antwort präzise und technisch. Der Nutzer ist Fachingenieur.
- Antworte auf Deutsch, sofern die Frage auf Deutsch gestellt wird."""


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


def chat(project_id: str, question: str) -> ChatResponse:
    sources = retrieve_sources(project_id, question)
    answer = generate_answer(question, sources)
    return ChatResponse(answer=answer, sources=sources)
