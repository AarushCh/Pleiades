import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from src import db

pytestmark = pytest.mark.skipif(db.SCHEMA is not None, reason="checked against SQLite without a schema")


def test_migrations_build_exactly_the_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    db.migrate(engine)
    with engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), db.Base.metadata) == []
    assert db.revision(engine) == db.head()


def test_a_database_made_before_migrations_is_adopted(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        command.upgrade(db.alembic_config(conn), "0001")
        conn.exec_driver_sql("DROP TABLE alembic_version")
    db.migrate(engine)
    assert db.revision(engine) == db.head()
