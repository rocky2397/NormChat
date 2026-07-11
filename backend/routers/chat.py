from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.chat import ChatRequest, ChatResponse
from models.project import Project
from services.llm import chat

router = APIRouter(prefix="/projects", tags=["chat"])


@router.post("/{project_id}/chat", response_model=ChatResponse)
def project_chat(
    project_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

    try:
        return chat(project_id, payload.question.strip())
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Anfrage konnte nicht verarbeitet werden: {exc}",
        ) from exc
