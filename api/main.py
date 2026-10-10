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
from src.db import (
    Conversation,
    Message,
    SessionLocal,
    Tenant,
    User,
    init_db,
    now,
    scope_to_tenant,
    seed_documents,
)
from src.ingest import build_index
from src.llm import first_answering
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
    STATE["bots"] = {}
    home = STATE["bots"][config.DEFAULT_TENANT] = await asyncio.to_thread(SupportAssistant)
    STATE["answering"], STATE["llm_failures"] = await asyncio.to_thread(
        first_answering, home.llm, home.models)
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


def bot(tenant: str | None = None) -> SupportAssistant:
    bots = STATE.get("bots")
    if bots is None:
        raise HTTPException(503, "Assistant is still starting")
    slug = (tenant or config.DEFAULT_TENANT).strip().lower()
    if slug not in bots:
        bots[slug] = SupportAssistant(tenant=slug)
    return bots[slug]


def tenant_slug(db: Session, user: User) -> str:
    row = db.get(Tenant, user.tenant_id)
    if row is None:
        raise HTTPException(404, "Unknown organisation")
    return row.slug


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.api_route("/api/health", methods=["GET", "HEAD"], response_model=HealthResponse)
def health() -> HealthResponse:
    b = bot()
    return HealthResponse(
        status="ok",
        backend=STATE.get("answering", b.backend_name),
        has_llm=not STATE.get("answering", b.backend_name).startswith("Extractive"),
        top_k=b.top_k,
        chunks=len(b.chunks),
        documents=list(config.SOURCE_LABELS.values()),
        database=STATE.get("database", "primary"),
        llm_failures=STATE.get("llm_failures", []),
    )


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> SearchResponse:
    b = bot(tenant_slug(db, user))
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
        if convo is None or convo.user_id != user.id or convo.tenant_id != user.tenant_id:
            raise HTTPException(404, "Conversation not found")
        return convo
    convo = Conversation(tenant_id=user.tenant_id, user_id=user.id)
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
    b = bot(tenant_slug(db, user))
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Question is empty")

    convo = _conversation(db, user, req.conversation_id)
    history = _history(convo)
    convo_id, tenant_id = convo.id, user.tenant_id
    is_first = not convo.messages

    async def events():
        start = time.perf_counter()
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce():
            try:
                for update in b.graph.stream({"question": question, "history": history},
                                             stream_mode="updates"):
                    loop.call_soon_threadsafe(queue.put_nowait, ("update", update))
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(exc)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

        task = asyncio.create_task(asyncio.to_thread(produce))
        r, tokens, turn = None, 0, {}
        while True:
            kind, payload = await queue.get()
            if kind == "done":
                break
            if kind == "error":
                yield sse("error", {"message": payload})
                break
            node, update = next(iter(payload.items()))
            turn.update(update or {})
            if node == "retrieve":
                r = update["retrieval"]
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
        await task

        answer = turn.get("answer", "")
        if answer:
            yield sse("token", {"text": answer})
        elapsed = round((time.perf_counter() - start) * 1000)

        if answer and r is not None:
            with SessionLocal() as write:
                scope_to_tenant(write, tenant_id)
                convo_row = write.get(Conversation, convo_id)
                if convo_row is not None:
                    write.add(Message(tenant_id=convo_row.tenant_id,
                                      conversation_id=convo_id, role="user", content=question))
                    write.add(Message(
                        tenant_id=convo_row.tenant_id,
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

        yield sse("done", {
            "total_ms": elapsed,
            "conversation_id": convo_id,
            "outcome": turn.get("outcome"),
            "unsupported": turn.get("unsupported", []),
            "attempts": turn.get("attempts", 0),
        })

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
        .where(Conversation.tenant_id == user.tenant_id, Conversation.user_id == user.id)
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
async def reseed(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user.email not in ADMINS:
        raise HTTPException(403, "Admin access required")
    synced = seed_documents(db, user.tenant_id)
    slug = tenant_slug(db, user)
    await asyncio.to_thread(build_index, slug)
    fresh = await asyncio.to_thread(SupportAssistant, slug)
    STATE["bots"][slug] = fresh
    return {"synced": synced, "chunks": len(fresh.chunks)}


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
