from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SourceOut(BaseModel):
    label: str
    section: str
    score: float | None
    retriever: str
    excerpt: str


class SearchResponse(BaseModel):
    query: str
    expansions: list[str]
    sources: list[SourceOut]
    elapsed_ms: float


class HealthResponse(BaseModel):
    status: str
    backend: str
    has_llm: bool
    top_k: int
    chunks: int
    documents: list[str]


class SessionResponse(BaseModel):
    session_id: str
    turns: int
