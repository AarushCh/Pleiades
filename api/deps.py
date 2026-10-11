from __future__ import annotations

import time
from collections import deque
from collections.abc import Generator

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src import config
from src.auth import decode_token
from src.db import SessionLocal, Tenant, User, scope_to_tenant

_HITS: dict[str, deque[float]] = {}
_SWEPT = [0.0]
COOKIE = "pleiades_session"


def client_ip(request: Request) -> str:
    chain = [ip.strip() for ip in request.headers.get("x-forwarded-for", "").split(",") if ip.strip()]
    if config.PROXY_HOPS and chain:
        return chain[-min(config.PROXY_HOPS, len(chain))]
    return request.client.host if request.client else "unknown"


def rate_limit(key: str, limit: int, window: float) -> None:
    clock = time.monotonic()
    if clock - _SWEPT[0] > 60:
        _SWEPT[0] = clock
        for stale in [k for k, hits in list(_HITS.items()) if not hits or clock - hits[-1] > 3600]:
            _HITS.pop(stale, None)
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
    scope_to_tenant(db, tenant.id)
    return tenant


def current_user(
    authorization: str | None = Header(default=None),
    session: str | None = Cookie(default=None, alias=COOKIE),
    db: Session = Depends(get_db),
) -> User:
    bearer = authorization and authorization.lower().startswith("bearer ")
    token = authorization.split(" ", 1)[1].strip() if bearer else session
    if not token:
        raise HTTPException(401, "Not authenticated")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Session expired, sign in again")

    try:
        tenant_id = int(payload["tid"])
        version = int(payload.get("ver", 1))
        scope_to_tenant(db, tenant_id)
        user = db.get(User, int(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "Session expired, sign in again") from None
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(401, "Account no longer exists")
    if version != user.session_version:
        raise HTTPException(401, "Session expired, sign in again")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user
