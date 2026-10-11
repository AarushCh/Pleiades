import sqlalchemy as sa
from alembic import op

from src.db import SCHEMA, schema_for

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def where() -> str | None:
    return schema_for(op.get_bind())


def ref(table: str) -> str:
    return f"{where()}.{table}.id" if where() else f"{table}.id"


def ix(table: str, column: str) -> str:
    return f"ix_{SCHEMA}_{table}_{column}" if SCHEMA else f"ix_{table}_{column}"


def key(name: str, table: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey(ref(table), ondelete="CASCADE"), nullable=False)


def stamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def indexed(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(ix(table, column), table, [column], schema=where())


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        stamp("created_at"),
        schema=where(),
    )
    op.create_index(ix("tenants", "slug"), "tenants", ["slug"], unique=True, schema=where())
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        key("tenant_id", "tenants"),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        stamp("created_at"),
        sa.UniqueConstraint("tenant_id", "email"),
        schema=where(),
    )
    indexed("users", "tenant_id", "email")
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        key("tenant_id", "tenants"),
        key("user_id", "users"),
        sa.Column("title", sa.String(200), nullable=False),
        stamp("created_at"),
        stamp("updated_at"),
        schema=where(),
    )
    indexed("conversations", "tenant_id", "user_id")
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        key("tenant_id", "tenants"),
        key("conversation_id", "conversations"),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        stamp("created_at"),
        schema=where(),
    )
    indexed("messages", "tenant_id", "conversation_id")
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        key("tenant_id", "tenants"),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        stamp("updated_at"),
        sa.UniqueConstraint("tenant_id", "filename"),
        schema=where(),
    )
    indexed("documents", "tenant_id", "filename")


def downgrade() -> None:
    for table in ("documents", "messages", "conversations", "users", "tenants"):
        op.drop_table(table, schema=where())
