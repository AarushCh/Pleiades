import sqlalchemy as sa
from alembic import op

from src.db import schema_for

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
                  schema=schema_for(op.get_bind()))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=schema_for(op.get_bind())) as batch:
        batch.drop_column("is_admin")
