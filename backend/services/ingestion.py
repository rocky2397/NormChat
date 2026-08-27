import logging
from pathlib import Path

from sqlalchemy.orm import Session

from config import settings
from models.document import Document
from services.chunking import (
    chunk_pages,
    extract_pages,
    strip_boilerplate,
    strip_front_matter,
)
from services.embeddings import get_embeddings
from services.norm_identity import parse_identity
from services.reference_resolution import enrich_project_references
from services.storage import (
    bump_collection_version,
    extract_norm_reference,
    get_collection,
    get_project_documents_dir,
)

logger = logging.getLogger(__name__)


def ingest_document(
    db: Session,
    project_id: str,
    filename: str,
    file_bytes: bytes,
    enrich: bool = True,
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
    identity = parse_identity(safe_name, first_page_text)
    norm_reference = (
        identity.reference
        if identity
        else extract_norm_reference(safe_name, first_page_text)
    )
    # Boilerplate detection first: it needs every page to spot the running
    # header, and blanking pages beforehand would weaken that signal.
    cleaned_pages, header_edition = strip_boilerplate(pages, norm_reference)
    cleaned_pages = strip_front_matter(cleaned_pages)
    # The cover declares the edition outright ("Ausgabe: 2015-02-15"); the
    # header-derived one is inferred from whatever line repeats across pages,
    # so it only stands in for documents no profile recognises.
    edition = (identity.edition if identity else None) or header_edition
    chunks = chunk_pages(cleaned_pages, norm_reference)

    document = Document(
        project_id=project_id,
        filename=safe_name,
        norm_reference=norm_reference,
        edition=edition,
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
                "edition": edition or "",
            }
            for chunk in chunks
        ]
        collection.add(
            ids=ids,
            embeddings=vectors,
            documents=texts,
            metadatas=metadatas,
        )

    bump_collection_version(project_id)
    db.commit()
    db.refresh(document)

    # A national annex may arrive before the norm it modifies, so reference
    # enrichment runs as a project-level pass after ingestion rather than
    # once inside it. Because the pass scans the whole project, batch
    # callers pass enrich=False per document and call run_enrichment_pass()
    # once after the last one.
    if enrich:
        run_enrichment_pass(project_id)
    return document


def run_enrichment_pass(project_id: str) -> None:
    # Ingested documents are committed before this runs: enrichment only
    # changes what is searchable, so a failure here must not fail an
    # otherwise completed upload.
    if not settings.reference_enrichment_enabled:
        return
    try:
        enrich_project_references(project_id)
    except Exception:
        logger.exception("Reference enrichment failed for project %s", project_id)
    finally:
        # Bumped even when the pass fails: it re-embeds as it goes, so a
        # failure part-way through still leaves the collection changed.
        bump_collection_version(project_id)


def delete_document_vectors(project_id: str, document_id: str) -> None:
    collection = get_collection(project_id)
    existing = collection.get(where={"document_id": document_id})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])
        bump_collection_version(project_id)


def remove_document_file(file_path: str) -> None:
    path = Path(file_path)
    if path.exists():
        path.unlink()
