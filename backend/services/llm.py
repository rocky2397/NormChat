from langchain_openai import ChatOpenAI

from config import settings
from models.chat import ChatResponse, SourceChunk
from services.embeddings import get_embeddings
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
        blocks.append(
            f"[Quelle {i}] {ref}, Seite {source.page_number}:\n{source.chunk_text}"
        )
    return "\n\n".join(blocks)


def retrieve_sources(project_id: str, question: str) -> list[SourceChunk]:
    embeddings = get_embeddings()
    query_vector = embeddings.embed_query(question)
    collection = get_collection(project_id)

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=settings.top_k_chunks,
        include=["documents", "metadatas", "distances"],
    )

    sources: list[SourceChunk] = []
    if not results["documents"] or not results["documents"][0]:
        return sources

    for doc_text, metadata in zip(results["documents"][0], results["metadatas"][0]):
        sources.append(
            SourceChunk(
                document_id=metadata["document_id"],
                filename=metadata["source_filename"],
                page_number=int(metadata["page_number"]),
                chunk_text=doc_text,
                norm_reference=metadata.get("norm_reference") or None,
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
