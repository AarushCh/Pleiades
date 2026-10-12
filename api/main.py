from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import sys
import time
import traceback
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.deps import admin_user, current_user, get_db, rate_limit
from api.routes_auth import router as auth_router
from api.schemas import (
    ChatRequest,
    ConversationOut,
    FeedbackRequest,
    HealthResponse,
    MessageOut,
    RenameRequest,
    SearchRequest,
    SearchResponse,
)
from src import config
from src import db as storage
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
from src.embeddings import embedder_tag
from src.ingest import build_index
from src.llm import first_answering
from src.rag import SupportAssistant

STATE: dict = {}
DIST = Path(__file__).resolve().parent.parent / "frontend" / "out"
ORIGINS = config.CORS_ORIGINS


@asynccontextmanager
async def lifespan(_: FastAPI):
    STATE["database"] = await asyncio.to_thread(init_db)
    if not config.CHROMA_DIR.exists():
        raise RuntimeError("No vector index. Run: python -m src.ingest")
    STATE["bots"] = {}
    home = STATE["bots"][config.DEFAULT_TENANT] = await asyncio.to_thread(assistant, config.DEFAULT_TENANT)
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


@cache
def content_security_policy(_built: int) -> str:
    bodies = {b for page in DIST.glob("**/*.html")
              for b in re.findall(r"<script>(.*?)</script>", page.read_text(encoding="utf-8"), re.S)}
    hashes = " ".join(sorted(f"'sha256-{base64.b64encode(hashlib.sha256(b.encode()).digest()).decode()}'"
                             for b in bodies))
    return (f"default-src 'self'; script-src 'self' {hashes}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'")


SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    index = DIST / "index.html"
    response.headers["Content-Security-Policy"] = content_security_policy(
        index.stat().st_mtime_ns if index.exists() else 0)
    return response


def bot(tenant: str | None = None) -> SupportAssistant:
    bots = STATE.get("bots")
    if bots is None:
        raise HTTPException(503, "Assistant is still starting")
    slug = (tenant or config.DEFAULT_TENANT).strip().lower()
    if slug not in bots:
        bots[slug] = assistant(slug)
    return bots[slug]


def assistant(slug: str) -> SupportAssistant:
    with SessionLocal() as session:
        name = session.scalar(select(Tenant.name).where(Tenant.slug == slug))
    return SupportAssistant(tenant=slug, organisation=name or config.DEFAULT_TENANT_NAME)


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
        embedder=embedder_tag() or "all-MiniLM-L6-v2",
        documents=list(config.SOURCE_LABELS.values()),
        database=STATE.get("database", "primary"),
        llm_failures=STATE.get("llm_failures", []),
        schema_revision=storage.head(),
        rls=storage.RLS,
    )


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> SearchResponse:
    b = bot(tenant_slug(db, user))
    if not user.is_admin:
        rate_limit(f"chat:{user.id}", 6, 60)
    start = time.perf_counter()
    r = await asyncio.to_thread(b.retrieve, req.query, [], req.top_k, user.is_admin)
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


def turns_today(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count(Message.id)).join(Conversation).where(
            Conversation.user_id == user.id,
            Message.role == "assistant",
            Message.created_at >= now() - timedelta(days=1),
        )) or 0


@app.get("/api/usage")
def usage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"used": turns_today(db, user), "limit": None if user.is_admin else config.CHAT_DAILY_LIMIT}


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
    if not user.is_admin:
        rate_limit(f"chat:{user.id}", 6, 60)
        if turns_today(db, user) >= config.CHAT_DAILY_LIMIT:
            raise HTTPException(429, f"You've used today's {config.CHAT_DAILY_LIMIT} questions. "
                                     "They free up again over the next 24 hours.")

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
            except Exception:
                traceback.print_exc()
                loop.call_soon_threadsafe(queue.put_nowait, (
                    "error", "Something went wrong while answering. Please try again in a moment."))
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

        message_id = None
        if answer and r is not None:
            with SessionLocal() as write:
                scope_to_tenant(write, tenant_id)
                convo_row = write.get(Conversation, convo_id)
                if convo_row is not None:
                    write.add(Message(tenant_id=convo_row.tenant_id,
                                      conversation_id=convo_id, role="user", content=question))
                    reply = Message(
                        tenant_id=convo_row.tenant_id,
                        conversation_id=convo_id,
                        role="assistant",
                        content=answer,
                        sources=json.dumps(b.sources(r), ensure_ascii=False),
                        prompt_tokens=tokens,
                        latency_ms=elapsed,
                        outcome=turn.get("outcome"),
                    )
                    write.add(reply)
                    if is_first:
                        convo_row.title = question[:80]
                    convo_row.updated_at = now()
                    write.commit()
                    message_id = reply.id

        yield sse("done", {
            "total_ms": elapsed,
            "conversation_id": convo_id,
            "message_id": message_id,
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
            id=m.id,
            role=m.role,
            content=m.content,
            sources=json.loads(m.sources) if m.sources else None,
            prompt_tokens=m.prompt_tokens,
            latency_ms=m.latency_ms,
            rating=m.rating,
            outcome=m.outcome,
            handover=m.handover_at is not None,
        )
        for m in convo.messages
    ]


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: int,
    req: RenameRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    title = " ".join(req.title.split())
    if not title:
        raise HTTPException(422, "Title is empty")
    _conversation(db, user, conversation_id).title = title
    db.commit()
    return {"id": conversation_id, "title": title}


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


def _own_answer(db: Session, user: User, message_id: int) -> Message:
    message = db.get(Message, message_id)
    if (message is None or message.role != "assistant" or message.tenant_id != user.tenant_id
            or message.conversation.user_id != user.id):
        raise HTTPException(404, "Message not found")
    return message


@app.post("/api/messages/{message_id}/handover")
def request_handover(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    message = _own_answer(db, user, message_id)
    message.handover_at = message.handover_at or now()
    db.commit()
    return {"handover": message_id}


@app.post("/api/messages/{message_id}/feedback")
def rate(message_id: int, req: FeedbackRequest, user: User = Depends(current_user),
         db: Session = Depends(get_db)) -> dict:
    message = _own_answer(db, user, message_id)
    message.rating = req.rating
    message.feedback = (req.reason or "").strip() or None
    db.commit()
    return {"rated": message_id}


def _queue(db: Session, rows) -> list[dict]:
    return [{
        "id": m.id,
        "question": db.scalar(select(Message.content).where(
            Message.conversation_id == m.conversation_id, Message.role == "user", Message.id < m.id)
            .order_by(Message.id.desc()).limit(1)),
        "answer": m.content,
        "reason": m.feedback,
        "email": m.conversation.user.email,
        "asked_for_person": m.handover_at is not None,
        "sources": json.loads(m.sources) if m.sources else [],
        "created_at": m.created_at,
    } for m in rows]


@app.get("/api/admin/feedback")
def triage(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return _queue(db, db.scalars(select(Message).where(Message.tenant_id == user.tenant_id, Message.rating == -1)
                                 .order_by(Message.id.desc()).limit(100)).all())


@app.get("/api/admin/handovers")
def handovers(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return _queue(db, db.scalars(select(Message).where(
        Message.tenant_id == user.tenant_id,
        or_(Message.outcome == "escalated", Message.handover_at.is_not(None)))
        .order_by(Message.id.desc()).limit(100)).all())


@app.get("/api/admin/overview")
def overview(days: int = 7, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    days = max(1, min(days, 90))
    recent = (Message.tenant_id == user.tenant_id, Message.role == "assistant",
              Message.created_at >= now() - timedelta(days=days))
    counts = {"questions": 0, "handed_over": 0, "helpful": 0, "not_helpful": 0}
    asked = Message.handover_at.is_not(None)
    for outcome, rating, requested, n in db.execute(
            select(Message.outcome, Message.rating, asked, func.count())
            .where(*recent).group_by(Message.outcome, Message.rating, asked)):
        counts["questions"] += n
        counts["handed_over"] += n if outcome == "escalated" or requested else 0
        counts["helpful"] += n if rating == 1 else 0
        counts["not_helpful"] += n if rating == -1 else 0
    people = db.scalar(select(func.count(func.distinct(Conversation.user_id)))
                       .join(Message, Message.conversation_id == Conversation.id).where(*recent)) or 0
    return {"days": days, **counts, "answered": counts["questions"] - counts["handed_over"], "people": people}


@app.get("/api/admin/join-code")
def join_code(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    return {"join_code": db.get(Tenant, user.tenant_id).join_code}


@app.post("/api/admin/join-code")
def new_join_code(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    tenant = db.get(Tenant, user.tenant_id)
    tenant.join_code = secrets.token_urlsafe(12)
    db.commit()
    return {"join_code": tenant.join_code}


@app.delete("/api/admin/join-code")
def open_signup(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    db.get(Tenant, user.tenant_id).join_code = None
    db.commit()
    return {"join_code": None}


@app.post("/api/admin/reseed")
async def reseed(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    synced = seed_documents(db, user.tenant_id)
    slug = tenant_slug(db, user)
    await asyncio.to_thread(build_index, slug)
    fresh = await asyncio.to_thread(assistant, slug)
    STATE["bots"][slug] = fresh
    return {"synced": synced, "chunks": len(fresh.chunks)}


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
