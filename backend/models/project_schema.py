from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    bundesland: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    bundesland: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    norm_reference: str | None
    page_count: int
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
