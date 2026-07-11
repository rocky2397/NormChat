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


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
