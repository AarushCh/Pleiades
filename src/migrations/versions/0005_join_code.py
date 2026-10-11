import sqlalchemy as sa
from alembic import op

from src.db import SCHEMA

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("join_code", sa.String(64), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    with op.batch_alter_table("tenants", schema=SCHEMA) as batch:
        batch.drop_column("join_code")
