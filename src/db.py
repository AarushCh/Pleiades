from __future__ import annotations

import os
import re
import secrets
import sys
from datetime import UTC, datetime
from functools import cache
from urllib.parse import urlsplit, urlunsplit

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from src import config


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    return normalised(url) if url else f"sqlite:///{config.ROOT / 'pleiades.db'}"


def normalised(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


URL = database_url()
IS_SQLITE = URL.startswith("sqlite")
IS_POOLED = "pooler." in URL or ":6543" in URL
SCHEMA = None if IS_SQLITE else os.getenv("DB_SCHEMA", "pleiades")
RLS = os.getenv("DB_RLS", "").strip().lower() in {"1", "true", "yes"} and not IS_SQLITE
TENANT_TABLES = ("users", "conversations", "messages", "documents")


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
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def _tenant_fk() -> Mapped[int]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("tenant_id", "filename"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = _tenant_fk()
    filename: Mapped[str] = mapped_column(String(200), index=True)
    label: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


def ensure_tenant(session: Session, slug: str, name: str | None = None) -> Tenant:
    slug = slug.strip().lower()
    row = session.scalar(select(Tenant).where(Tenant.slug == slug))
    if row is None:
        row = Tenant(slug=slug, name=name or slug.replace("-", " ").title())
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::int"
APP_ROLE = os.getenv("DB_APP_ROLE", "pleiades_app")


def create_schema(bind) -> None:
    if SCHEMA:
        with bind.begin() as conn:
            if conn.execute(text("SELECT 1 FROM pg_namespace WHERE nspname = :s"), {"s": SCHEMA}).first() is None:
                conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))


def alembic_config(connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(config.ROOT / "src" / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


@cache
def head() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def _schema_for(conn) -> str | None:
    return None if conn.dialect.name == "sqlite" else SCHEMA


def revision(bind) -> str | None:
    with bind.connect() as conn:
        return MigrationContext.configure(
            conn, opts={"version_table_schema": _schema_for(conn)}).get_current_revision()


def migrate(bind) -> None:
    with bind.begin() as conn:
        tables = inspect(conn).get_table_names(schema=_schema_for(conn))
        cfg = alembic_config(conn)
        if "users" in tables and "alembic_version" not in tables:
            command.stamp(cfg, "0001")
        command.upgrade(cfg, "head")


def apply_rls(bind) -> None:
    qualified = f'"{SCHEMA}".' if SCHEMA else ""
    with bind.begin() as conn:
        for table in TENANT_TABLES:
            conn.execute(text(f'ALTER TABLE {qualified}"{table}" ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE {qualified}"{table}" FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON {qualified}"{table}"'))
            conn.execute(text(
                f'CREATE POLICY tenant_isolation ON {qualified}"{table}" '
                f"USING (tenant_id = {TENANT_SETTING}) WITH CHECK (tenant_id = {TENANT_SETTING})"))


def grant_app_role(bind, role: str) -> None:
    with bind.begin() as conn:
        for statement in (
            f'GRANT USAGE ON SCHEMA "{SCHEMA}" TO "{role}"',
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{SCHEMA}" TO "{role}"',
            f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{SCHEMA}" TO "{role}"',
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{SCHEMA}" GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"',
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{SCHEMA}" GRANT USAGE, SELECT ON SEQUENCES TO "{role}"',
        ):
            conn.execute(text(statement))


def verify_rls(bind) -> None:
    with bind.connect() as conn:
        role, bypass = conn.execute(text(
            "SELECT rolname, rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user")).one()
        if bypass:
            raise RuntimeError(
                f"DB_RLS is on, but the database role {role!r} bypasses row-level security, so the "
                "policies would never apply. Connect as the app role that `python -m src.db setup` creates.")
        enforced = {name for name, on, forced, policy in conn.execute(text(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, EXISTS (SELECT 1 FROM pg_policies p "
            "WHERE p.schemaname = n.nspname AND p.tablename = c.relname AND p.policyname = 'tenant_isolation') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND c.relname = ANY(:t)"), {"s": SCHEMA, "t": list(TENANT_TABLES)})
            if on and forced and policy}
    missing = [t for t in TENANT_TABLES if t not in enforced]
    if missing:
        raise RuntimeError(f"Row-level security is not enforced on {missing}. Run `python -m src.db setup` "
                           "with DATABASE_ADMIN_URL set to the database owner's connection string.")


def _set_tenant(connection, tenant_id: int) -> None:
    connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})


@event.listens_for(Session, "after_begin")
def _scope_each_transaction(session, transaction, connection) -> None:
    if RLS and session.info.get("tenant_id") is not None:
        _set_tenant(connection, session.info["tenant_id"])


def scope_to_tenant(session: Session, tenant_id: int) -> None:
    session.info["tenant_id"] = tenant_id
    if RLS and session.in_transaction():
        _set_tenant(session.connection(), tenant_id)


def init_db() -> str:
    global RLS
    try:
        if RLS:
            current, needed = revision(engine), head()
            if current != needed:
                raise RuntimeError(
                    f"The database schema is at revision {current or 'none'} and this code needs {needed}. "
                    "Run `python -m src.db setup` with DATABASE_ADMIN_URL set to the owner's connection string.")
            verify_rls(engine)
        else:
            create_schema(engine)
            migrate(engine)
        with SessionLocal() as session:
            ensure_tenant(session, config.DEFAULT_TENANT, config.DEFAULT_TENANT_NAME)
        return "primary"
    except OperationalError:
        if IS_SQLITE:
            raise
    RLS = False
    fallback = create_engine(
        f"sqlite:///{config.ROOT / 'pleiades.db'}",
        connect_args={"check_same_thread": False},
    ).execution_options(schema_translate_map={SCHEMA: None})
    SessionLocal.configure(bind=fallback)
    migrate(fallback)
    with SessionLocal() as session:
        ensure_tenant(session, config.DEFAULT_TENANT, config.DEFAULT_TENANT_NAME)
    return "fallback"


def seed_documents(session: Session, tenant_id: int | None = None) -> int:
    if tenant_id is None:
        tenant_id = ensure_tenant(session, config.DEFAULT_TENANT, config.DEFAULT_TENANT_NAME).id
    scope_to_tenant(session, tenant_id)
    written = 0
    for path in sorted(config.DATA_DIR.glob("**/*.md")):
        body = path.read_text(encoding="utf-8")
        label = config.SOURCE_LABELS.get(path.name, path.name)
        row = session.scalar(select(Document).where(
            Document.tenant_id == tenant_id, Document.filename == path.name))
        if row is None:
            session.add(Document(tenant_id=tenant_id, filename=path.name, label=label, body=body))
            written += 1
        elif row.body != body or row.label != label:
            row.body, row.label = body, label
            written += 1
    session.commit()
    return written


def load_documents_from_db(tenant: str | None = None) -> list[tuple[str, str, str]]:
    slug = (tenant or config.DEFAULT_TENANT).strip().lower()
    with SessionLocal() as session:
        row = session.scalar(select(Tenant).where(Tenant.slug == slug))
        if row is None:
            return []
        scope_to_tenant(session, row.id)
        rows = session.scalars(
            select(Document).where(Document.tenant_id == row.id).order_by(Document.filename)
        ).all()
        return [(r.filename, r.label, r.body) for r in rows]


def stats() -> dict:
    with SessionLocal() as session:
        return {
            "tenants": session.scalar(select(func.count()).select_from(Tenant)) or 0,
            "users": session.scalar(select(func.count()).select_from(User)) or 0,
            "conversations": session.scalar(select(func.count()).select_from(Conversation)) or 0,
            "messages": session.scalar(select(func.count()).select_from(Message)) or 0,
            "documents": session.scalar(select(func.count()).select_from(Document)) or 0,
        }


def setup(admin_url: str) -> str | None:
    admin = create_engine(normalised(admin_url), connect_args=_connect_args())
    create_schema(admin)
    migrate(admin)
    apply_rls(admin)
    password = None
    with admin.begin() as conn:
        if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE}).first() is None:
            password = secrets.token_urlsafe(32)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", password):
                raise RuntimeError("Generated password has unexpected characters")
            conn.execute(text(f'CREATE ROLE "{APP_ROLE}" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '
                              + f"'{password}'"))
    grant_app_role(admin, APP_ROLE)
    with sessionmaker(bind=admin, expire_on_commit=False)() as session:
        seed_documents(session, ensure_tenant(session, config.DEFAULT_TENANT, config.DEFAULT_TENANT_NAME).id)
    if password is None:
        return None
    parts = urlsplit(admin_url)
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=f"{APP_ROLE}:{password}@{host}"))


def write_env(key: str, value: str) -> None:
    path = config.ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if not line.startswith(f"{key}=")] + [f"{key}={value}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__" and sys.argv[1:] == ["setup"]:
    owner = os.getenv("DATABASE_ADMIN_URL", "").strip()
    if not owner:
        raise SystemExit("Set DATABASE_ADMIN_URL to the database owner's connection string")
    app_url = setup(owner)
    if app_url:
        write_env("DATABASE_URL", app_url)
        print(f"Created role {APP_ROLE}; its connection string is now DATABASE_URL in .env")
    print(f"Schema '{SCHEMA}': tables, row-level security, grants to {APP_ROLE} and documents are in place")
elif __name__ == "__main__":
    init_db()
    with SessionLocal() as s:
        n = seed_documents(s)
    print(f"Schema '{SCHEMA or 'main'}' ready on {URL.split('@')[-1]}")
    print(f"Documents synced: {n}")
    print(stats())
