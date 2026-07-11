from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from db.database import get_db
from models.project import Project
from models.project_schema import DocumentResponse
from models.document import Document
from services.ingestion import delete_document_vectors, ingest_document, remove_document_file

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
    response_model=DocumentResponse,
    status_code=201,
)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Nur PDF-Dateien werden unterstützt")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Leere Datei")

    try:
        document = ingest_document(db, project_id, file.filename, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Dokument konnte nicht verarbeitet werden: {exc}",
        ) from exc

    return document


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


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    delete_document_vectors(document.project_id, document.id)
    remove_document_file(document.file_path)
    db.delete(document)
    db.commit()
