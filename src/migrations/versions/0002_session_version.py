import sqlalchemy as sa
from alembic import op

from src.db import schema_for

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
                  schema=schema_for(op.get_bind()))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=schema_for(op.get_bind())) as batch:
        batch.drop_column("session_version")
