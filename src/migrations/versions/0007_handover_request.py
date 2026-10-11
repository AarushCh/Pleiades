import sqlalchemy as sa
from alembic import op

from src.db import SCHEMA

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("handover_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    with op.batch_alter_table("messages", schema=SCHEMA) as batch:
        batch.drop_column("handover_at")
