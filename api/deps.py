from __future__ import annotations

import time
from collections import deque
from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src import config
from src.auth import decode_token
from src.db import SessionLocal, Tenant, User, scope_to_tenant

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


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_tenant(
    x_tenant: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Tenant:
    slug = (x_tenant or config.DEFAULT_TENANT).strip().lower()
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise HTTPException(404, "Unknown organisation")
    return tenant


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
        tenant_id = int(payload["tid"])
        scope_to_tenant(db, tenant_id)
        user = db.get(User, int(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "Session expired, sign in again") from None
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(401, "Account no longer exists")
    return user
