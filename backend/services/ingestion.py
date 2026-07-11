from pathlib import Path

from sqlalchemy.orm import Session

from models.document import Document
from services.chunking import chunk_pages, extract_pages
from services.embeddings import get_embeddings
from services.storage import (
    extract_norm_reference,
    get_collection,
    get_project_documents_dir,
)


def ingest_document(
    db: Session,
    project_id: str,
    filename: str,
    file_bytes: bytes,
) -> Document:
    docs_dir = get_project_documents_dir(project_id)
    safe_name = Path(filename).name
    dest_path = docs_dir / safe_name

    counter = 1
    while dest_path.exists():
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        dest_path = docs_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    dest_path.write_bytes(file_bytes)

    pages = extract_pages(str(dest_path))
    first_page_text = pages[0].text if pages else ""
    norm_reference = extract_norm_reference(safe_name, first_page_text)
    chunks = chunk_pages(pages, norm_reference)

    document = Document(
        project_id=project_id,
        filename=safe_name,
        norm_reference=norm_reference,
        file_path=str(dest_path),
        page_count=len(pages),
        chunk_count=len(chunks),
    )
    db.add(document)
    db.flush()

    if chunks:
        embeddings = get_embeddings()
        texts = [chunk.text for chunk in chunks]
        vectors = embeddings.embed_documents(texts)
        collection = get_collection(project_id)

        ids = [f"{document.id}_{chunk.chunk_index}" for chunk in chunks]
        metadatas = [
            {
                "document_id": document.id,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "source_filename": safe_name,
                "norm_reference": chunk.norm_reference or "",
            }
            for chunk in chunks
        ]
        collection.add(
            ids=ids,
            embeddings=vectors,
            documents=texts,
            metadatas=metadatas,
        )

    db.commit()
    db.refresh(document)
    return document


def delete_document_vectors(project_id: str, document_id: str) -> None:
    collection = get_collection(project_id)
    existing = collection.get(where={"document_id": document_id})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])


def remove_document_file(file_path: str) -> None:
    path = Path(file_path)
    if path.exists():
        path.unlink()
