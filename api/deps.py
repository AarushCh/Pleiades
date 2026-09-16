from __future__ import annotations

import time
from collections import deque
from typing import Generator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from src import config
from src.auth import decode_token
from src.db import SessionLocal, User

_HITS: dict[str, deque[float]] = {}


def client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(key: str, limit: int, window: float) -> None:
    clock = time.monotonic()
    if len(_HITS) > 10_000:
        _HITS.clear()
    hits = _HITS.setdefault(key, deque())
    while hits and clock - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(429, "Too many attempts, try again shortly")
    hits.append(clock)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")

    payload = decode_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(401, "Session expired, sign in again")

    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        user = None
    if user is None:
        raise HTTPException(401, "Account no longer exists")
    return user
