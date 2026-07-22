from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)


class SourceChunk(BaseModel):
    document_id: str
    filename: str
    page_number: int
    chunk_text: str
    norm_reference: str | None = None
    edition: str | None = None
    highlight_snippet: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]


class FeedbackRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    sources: list[SourceChunk] = []
    rating: Literal["good", "mid", "bad"]
    comment: str | None = None


class FeedbackResponse(BaseModel):
    id: str
    project_id: str
    question: str
    answer: str
    rating: Literal["good", "mid", "bad"]
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
