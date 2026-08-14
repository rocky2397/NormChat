from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from db.database import get_db
from models.project import Project
from models.project_schema import DocumentResponse
from models.document import Document
from services.ingestion import (
    delete_document_vectors,
    ingest_document,
    remove_document_file,
    run_enrichment_pass,
)
from services.pdf_highlight import build_highlighted_copy

router = APIRouter(tags=["documents"])


@router.get("/projects/{project_id}/documents", response_model=list[DocumentResponse])
def list_documents(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return (
        db.query(Document)
        .filter(Document.project_id == project_id)
        .order_by(Document.created_at.desc())
        .all()
    )


@router.post(
    "/projects/{project_id}/documents",
    response_model=list[DocumentResponse],
    status_code=201,
)
async def upload_documents(
    project_id: str,
    file: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

    for upload in file:
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Nur PDF-Dateien werden unterstützt")

    # The enrichment pass scans the whole project, so a batch ingests every
    # file with enrich=False and runs the pass once at the end. The finally
    # covers partial failure: files ingested before the failing one are
    # committed and must not be left unenriched.
    documents = []
    try:
        for upload in file:
            file_bytes = await upload.read()
            if not file_bytes:
                raise HTTPException(status_code=400, detail="Leere Datei")
            try:
                documents.append(
                    ingest_document(
                        db, project_id, upload.filename, file_bytes, enrich=False
                    )
                )
            except ValueError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Dokument konnte nicht verarbeitet werden: {exc}",
                ) from exc
    finally:
        if documents:
            run_enrichment_pass(project_id)

    return documents


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    path = Path(document.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.filename,
    )


@router.get("/documents/{document_id}/highlighted")
def get_highlighted_document_file(
    document_id: str,
    page: int,
    text: str = "",
    db: Session = Depends(get_db),
):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    path = Path(document.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    highlighted_path = build_highlighted_copy(path, page, text)
    return FileResponse(
        highlighted_path,
        media_type="application/pdf",
        filename=document.filename,
        content_disposition_type="inline",
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    delete_document_vectors(document.project_id, document.id)
    remove_document_file(document.file_path)
    db.delete(document)
    db.commit()
