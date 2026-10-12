from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import STATE, app
from src import config
from src.db import Document, SessionLocal, Tenant


def test_startup_brings_stored_documents_and_the_index_up_to_date_with_the_files():
    with TestClient(app):
        pass
    with SessionLocal() as session:
        home = session.scalar(select(Tenant).where(Tenant.slug == config.DEFAULT_TENANT))
        row = session.scalar(select(Document).where(Document.tenant_id == home.id,
                                                    Document.filename == "help_centre.md"))
        row.body = "# Help Centre\n\n## Stale\nThis answer was replaced long ago."
        session.commit()
    with TestClient(app):
        bot = STATE["bots"][config.DEFAULT_TENANT]
        assert not any("replaced long ago" in c.page_content for c in bot.chunks)
        assert {c.metadata["hash"] for c in bot.chunks} <= set(bot.store.get(include=[])["ids"])
