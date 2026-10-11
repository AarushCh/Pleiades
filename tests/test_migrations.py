import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from src import db

pytestmark = pytest.mark.skipif(db.SCHEMA is not None, reason="checked against SQLite without a schema")


def test_migrations_build_exactly_the_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    db.migrate(engine)
    with engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), db.Base.metadata) == []
    assert db.revision(engine) == db.head()
    assert db.missing_columns(engine) == []


def test_a_database_made_before_migrations_is_adopted(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        command.upgrade(db.alembic_config(conn), "0001")
        conn.exec_driver_sql("DROP TABLE alembic_version")
    db.migrate(engine)
    assert "session_version" in {c["name"] for c in inspect(engine).get_columns("users")}
    assert db.revision(engine) == db.head()


def test_a_database_missing_columns_is_caught(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drifted.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT)")
    gaps = db.missing_columns(engine)
    assert "users.tenant_id" in gaps
    assert "tenants.slug" in gaps


def test_a_fresh_fallback_migrates_while_a_postgres_schema_is_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "SCHEMA", "pleiades")
    engine = create_engine(f"sqlite:///{tmp_path / 'fallback.db'}").execution_options(
        schema_translate_map={"pleiades": None})
    db.migrate(engine)
    assert db.revision(engine) == db.head()
    assert "handover_at" in {c["name"] for c in inspect(engine).get_columns("messages")}
