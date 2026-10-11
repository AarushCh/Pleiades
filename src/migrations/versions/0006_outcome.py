import sqlalchemy as sa
from alembic import op

from src.db import schema_for

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("outcome", sa.String(16), nullable=True), schema=schema_for(op.get_bind()))


def downgrade() -> None:
    with op.batch_alter_table("messages", schema=schema_for(op.get_bind())) as batch:
        batch.drop_column("outcome")
