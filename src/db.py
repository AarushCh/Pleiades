from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    MetaData,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    text,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from src import config


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{config.ROOT / 'pleiades.db'}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


URL = database_url()
IS_SQLITE = URL.startswith("sqlite")
IS_POOLED = "pooler." in URL or ":6543" in URL
SCHEMA = None if IS_SQLITE else os.getenv("DB_SCHEMA", "pleiades")


def _connect_args() -> dict:
    if IS_SQLITE:
        return {"check_same_thread": False}
    args: dict = {"connect_timeout": 10}
    if IS_POOLED:
        args["prepare_threshold"] = None
    return args


engine = create_engine(
    URL,
    pool_pre_ping=True,
    pool_recycle=280,
    pool_size=5,
    max_overflow=5,
    connect_args=_connect_args(),
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("filename"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(200), index=True)
    label: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


def init_db() -> None:
    if SCHEMA:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    Base.metadata.create_all(engine)


def seed_documents(session: Session) -> int:
    written = 0
    for path in sorted(config.DATA_DIR.glob("**/*.md")):
        body = path.read_text(encoding="utf-8")
        label = config.SOURCE_LABELS.get(path.name, path.name)
        row = session.scalar(select(Document).where(Document.filename == path.name))
        if row is None:
            session.add(Document(filename=path.name, label=label, body=body))
            written += 1
        elif row.body != body or row.label != label:
            row.body, row.label = body, label
            written += 1
    session.commit()
    return written


def load_documents_from_db() -> list[tuple[str, str, str]]:
    with SessionLocal() as session:
        rows = session.scalars(select(Document).order_by(Document.filename)).all()
        return [(r.filename, r.label, r.body) for r in rows]


def stats() -> dict:
    with SessionLocal() as session:
        return {
            "users": session.scalar(select(func.count()).select_from(User)) or 0,
            "conversations": session.scalar(select(func.count()).select_from(Conversation)) or 0,
            "messages": session.scalar(select(func.count()).select_from(Message)) or 0,
            "documents": session.scalar(select(func.count()).select_from(Document)) or 0,
        }


if __name__ == "__main__":
    init_db()
    with SessionLocal() as s:
        n = seed_documents(s)
    print(f"Schema '{SCHEMA or 'main'}' ready on {URL.split('@')[-1]}")
    print(f"Documents synced: {n}")
    print(stats())
