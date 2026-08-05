from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import current_user, get_db
from src.auth import create_token, hash_password, validate_credentials, verify_password
from src.db import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    name: str
    email: str


@router.post("/signup", response_model=AuthResponse)
def signup(req: SignupRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = req.email.strip().lower()
    problem = validate_credentials(email, req.password)
    if problem:
        raise HTTPException(422, problem)

    user = User(email=email, name=req.name.strip(), password_hash=hash_password(req.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with that email already exists")

    db.refresh(user)
    return AuthResponse(token=create_token(user.id, user.email), name=user.name, email=user.email)


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = req.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    return AuthResponse(token=create_token(user.id, user.email), name=user.name, email=user.email)


@router.get("/me", response_model=AuthResponse)
def me(user: User = Depends(current_user)) -> AuthResponse:
    return AuthResponse(token="", name=user.name, email=user.email)
