from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from src.db import SCHEMA, Base, database_url, normalised, schema_for


def run(connection) -> None:
    schema = schema_for(connection)
    if SCHEMA and schema is None:
        connection = connection.execution_options(schema_translate_map={SCHEMA: None})
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        version_table_schema=schema,
        include_schemas=bool(schema),
        include_name=lambda name, kind, _parents: kind != "schema" or name == schema,
    )
    with context.begin_transaction():
        context.run_migrations()


shared = context.config.attributes.get("connection")
if shared is not None:
    run(shared)
else:
    with create_engine(normalised(os.getenv("DATABASE_ADMIN_URL", "").strip()) or database_url()).connect() as conn:
        run(conn)
