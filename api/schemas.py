from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


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
    database: str = "primary"


class ConversationOut(BaseModel):
    id: int
    title: str
    updated_at: datetime
    turns: int


class MessageOut(BaseModel):
    role: str
    content: str
    sources: list[SourceOut] | None = None
    prompt_tokens: int = 0
    latency_ms: int = 0
