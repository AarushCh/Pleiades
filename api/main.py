from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.schemas import (
    ChatRequest,
    HealthResponse,
    SearchRequest,
    SearchResponse,
    SessionResponse,
)
from api.sessions import SessionStore
from src import config
from src.rag import SupportAssistant

STATE: dict = {}
SESSIONS = SessionStore()
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.CHROMA_DIR.exists():
        raise RuntimeError("No vector index. Run: python -m src.ingest")
    STATE["bot"] = await asyncio.to_thread(SupportAssistant)
    yield
    STATE.clear()


app = FastAPI(
    title="Nimbus Support API",
    description="Retrieval-Augmented Generation over enterprise knowledge bases",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def bot() -> SupportAssistant:
    instance = STATE.get("bot")
    if instance is None:
        raise HTTPException(503, "Assistant is still starting")
    return instance


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    b = bot()
    return HealthResponse(
        status="ok",
        backend=b.backend_name,
        has_llm=b.has_llm,
        top_k=b.top_k,
        chunks=len(b.chunks),
        documents=list(config.SOURCE_LABELS.values()),
    )


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    b = bot()
    start = time.perf_counter()
    original_k = b.top_k
    if req.top_k:
        b.top_k = req.top_k
    try:
        r = await asyncio.to_thread(b.retrieve, req.query, [])
    finally:
        b.top_k = original_k
    return SearchResponse(
        query=r.query,
        expansions=r.expansions,
        sources=b.sources(r),
        elapsed_ms=(time.perf_counter() - start) * 1000,
    )


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    b = bot()
    session = SESSIONS.get(req.session_id)
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Question is empty")

    async def events():
        start = time.perf_counter()
        try:
            r = await asyncio.to_thread(b.retrieve, question, session.history)
        except Exception as exc:
            yield sse("error", {"message": f"Retrieval failed: {exc}"})
            return

        retrieval_ms = (time.perf_counter() - start) * 1000
        yield sse("meta", {
            "session_id": session.id,
            "backend": b.backend_name,
            "query": r.query,
            "condensed": r.condensed,
            "expansions": r.expansions,
            "sources": b.sources(r),
            "retrieval_ms": round(retrieval_ms, 1),
            "prompt_tokens": b.prompt_tokens(question, r, session.history),
        })

        chunks: list[str] = []
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce():
            try:
                for token in b.stream(question, r, session.history):
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
        if answer:
            session.history.append((question, answer))
            if len(session.history) > 20:
                del session.history[:-20]

        yield sse("done", {
            "total_ms": round((time.perf_counter() - start) * 1000, 1),
            "turns": len(session.history),
        })

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/session/{session_id}/reset", response_model=SessionResponse)
def reset_session(session_id: str) -> SessionResponse:
    s = SESSIONS.reset(session_id)
    return SessionResponse(session_id=s.id, turns=len(s.history))


@app.get("/api/session/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    s = SESSIONS.get(session_id)
    return SessionResponse(session_id=s.id, turns=len(s.history))


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
