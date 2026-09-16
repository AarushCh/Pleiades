from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.deps import current_user, get_db
from api.routes_auth import router as auth_router
from api.schemas import (
    ChatRequest,
    ConversationOut,
    HealthResponse,
    MessageOut,
    SearchRequest,
    SearchResponse,
)
from src import config
from src.db import Conversation, Message, SessionLocal, User, init_db, now, seed_documents
from src.rag import SupportAssistant

STATE: dict = {}
DIST = Path(__file__).resolve().parent.parent / "frontend" / "out"
ORIGINS = config.CORS_ORIGINS
ADMINS = config.ADMIN_EMAILS


@asynccontextmanager
async def lifespan(_: FastAPI):
    STATE["database"] = await asyncio.to_thread(init_db)
    if not config.CHROMA_DIR.exists():
        raise RuntimeError("No vector index. Run: python -m src.ingest")
    STATE["bot"] = await asyncio.to_thread(SupportAssistant)
    yield
    STATE.clear()


app = FastAPI(
    title="Pleiades API",
    description="Retrieval-Augmented Generation over enterprise knowledge bases",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


def bot() -> SupportAssistant:
    instance = STATE.get("bot")
    if instance is None:
        raise HTTPException(503, "Assistant is still starting")
    return instance


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.api_route("/api/health", methods=["GET", "HEAD"], response_model=HealthResponse)
def health() -> HealthResponse:
    b = bot()
    return HealthResponse(
        status="ok",
        backend=b.backend_name,
        has_llm=b.has_llm,
        top_k=b.top_k,
        chunks=len(b.chunks),
        documents=list(config.SOURCE_LABELS.values()),
        database=STATE.get("database", "primary"),
    )


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest, _: User = Depends(current_user)) -> SearchResponse:
    b = bot()
    start = time.perf_counter()
    r = await asyncio.to_thread(b.retrieve, req.query, [], req.top_k)
    return SearchResponse(
        query=r.query,
        expansions=r.expansions,
        sources=b.sources(r),
        elapsed_ms=(time.perf_counter() - start) * 1000,
    )


def _conversation(db: Session, user: User, conversation_id: int | None) -> Conversation:
    if conversation_id:
        convo = db.get(Conversation, conversation_id)
        if convo is None or convo.user_id != user.id:
            raise HTTPException(404, "Conversation not found")
        return convo
    convo = Conversation(user_id=user.id)
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


def _history(convo: Conversation) -> list[tuple[str, str]]:
    pairs, pending = [], None
    for m in convo.messages:
        if m.role == "user":
            pending = m.content
        elif pending is not None:
            pairs.append((pending, m.content))
            pending = None
    return pairs[-config.HISTORY_TURNS:]


@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    b = bot()
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Question is empty")

    convo = _conversation(db, user, req.conversation_id)
    history = _history(convo)
    convo_id = convo.id
    is_first = not convo.messages

    async def events():
        start = time.perf_counter()
        try:
            r = await asyncio.to_thread(b.retrieve, question, history)
        except Exception as exc:
            yield sse("error", {"message": f"Retrieval failed: {exc}"})
            return

        tokens = b.prompt_tokens(question, r, history)
        yield sse("meta", {
            "conversation_id": convo_id,
            "backend": b.backend_name,
            "query": r.query,
            "condensed": r.condensed,
            "expansions": r.expansions,
            "sources": b.sources(r),
            "retrieval_ms": round((time.perf_counter() - start) * 1000, 1),
            "prompt_tokens": tokens,
        })

        chunks: list[str] = []
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce():
            try:
                for token in b.stream(question, r, history):
                    loop.call_soon_threadsafe(queue.put_nowait, ("token", token))
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(exc)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

        task = asyncio.create_task(asyncio.to_thread(produce))
        while True:
            kind, payload = await queue.get()
            if kind == "done":
                break
            if kind == "error":
                yield sse("error", {"message": payload})
                break
            chunks.append(payload)
            yield sse("token", {"text": payload})
        await task

        answer = "".join(chunks).strip()
        elapsed = round((time.perf_counter() - start) * 1000)

        if answer:
            with SessionLocal() as write:
                convo_row = write.get(Conversation, convo_id)
                if convo_row is not None:
                    write.add(Message(conversation_id=convo_id, role="user", content=question))
                    write.add(Message(
                        conversation_id=convo_id,
                        role="assistant",
                        content=answer,
                        sources=json.dumps(b.sources(r), ensure_ascii=False),
                        prompt_tokens=tokens,
                        latency_ms=elapsed,
                    ))
                    if is_first:
                        convo_row.title = question[:80]
                    convo_row.updated_at = now()
                    write.commit()

        yield sse("done", {"total_ms": elapsed, "conversation_id": convo_id})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ConversationOut]:
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    ).all()
    return [
        ConversationOut(id=c.id, title=c.title, updated_at=c.updated_at, turns=len(c.messages))
        for c in rows
    ]


@app.get("/api/conversations/{conversation_id}", response_model=list[MessageOut])
def get_conversation(
    conversation_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    convo = _conversation(db, user, conversation_id)
    return [
        MessageOut(
            role=m.role,
            content=m.content,
            sources=json.loads(m.sources) if m.sources else None,
            prompt_tokens=m.prompt_tokens,
            latency_ms=m.latency_ms,
        )
        for m in convo.messages
    ]


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    convo = _conversation(db, user, conversation_id)
    db.delete(convo)
    db.commit()
    return {"deleted": conversation_id}


@app.post("/api/admin/reseed")
def reseed(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user.email not in ADMINS:
        raise HTTPException(403, "Admin access required")
    return {"synced": seed_documents(db)}


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
