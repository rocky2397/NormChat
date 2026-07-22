import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.chat import FeedbackRequest, FeedbackResponse
from models.feedback import ChatFeedback
from models.project import Project

router = APIRouter(prefix="/projects", tags=["feedback"])


@router.post("/{project_id}/feedback", response_model=FeedbackResponse, status_code=201)
def submit_feedback(
    project_id: str,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

    feedback = ChatFeedback(
        project_id=project_id,
        question=payload.question,
        answer=payload.answer,
        sources_json=json.dumps([s.model_dump() for s in payload.sources]),
        rating=payload.rating,
        comment=payload.comment.strip() if payload.comment else None,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback
