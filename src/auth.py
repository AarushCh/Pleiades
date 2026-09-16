from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from src import config

SECRET = config.JWT_SECRET
if not SECRET:
    if config.DATABASE_URL:
        raise RuntimeError("JWT_SECRET must be set when DATABASE_URL is configured")
    SECRET = secrets.token_urlsafe(32)
ALGORITHM = "HS256"
TOKEN_DAYS = config.TOKEN_DAYS

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_credentials(email: str, password: str) -> str | None:
    if not EMAIL_RE.match(email):
        return "Enter a valid email address"
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if len(password) > 200:
        return "Password is too long"
    return None


def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
