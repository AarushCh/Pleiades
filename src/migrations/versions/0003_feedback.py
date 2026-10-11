import sqlalchemy as sa
from alembic import op

from src.db import SCHEMA

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("rating", sa.SmallInteger(), nullable=True), schema=SCHEMA)
    op.add_column("messages", sa.Column("feedback", sa.Text(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    with op.batch_alter_table("messages", schema=SCHEMA) as batch:
        batch.drop_column("feedback")
        batch.drop_column("rating")
