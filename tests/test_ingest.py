from __future__ import annotations

from src import config
from src.embeddings import MiniLMEmbeddings
from src.ingest import load_documents, split_documents


def test_every_document_loads():
    docs = load_documents()
    assert len(docs) == len(config.SOURCE_LABELS)
    assert all(d.page_content.strip() for d in docs)
    assert {d.metadata["filename"] for d in docs} == set(config.SOURCE_LABELS)


def test_chunks_carry_source_metadata():
    chunks = split_documents(load_documents())
    assert chunks
    for c in chunks:
        assert c.metadata["source_label"] in config.SOURCE_LABELS.values()
        assert c.metadata["hash"]
        assert len(c.page_content) <= config.CHUNK_SIZE * 1.5


def test_chunk_hashes_are_unique_and_stable():
    first = split_documents(load_documents())
    second = split_documents(load_documents())
    hashes = [c.metadata["hash"] for c in first]
    assert len(hashes) == len(set(hashes))
    assert hashes == [c.metadata["hash"] for c in second]


def test_embeddings_are_384_dimensional():
    emb = MiniLMEmbeddings()
    vec = emb.embed_query("router will not connect")
    assert len(vec) == 384
    assert all(isinstance(v, float) for v in vec)


def test_index_matches_source_documents(assistant):
    assert assistant.store._collection.count() == len(assistant.chunks)


def test_unreachable_database_falls_back_to_sqlite():
    import os
    import subprocess
    import sys

    script = (
        "from src.db import init_db, SessionLocal, User\n"
        "from sqlalchemy import select, func\n"
        "assert init_db() == 'fallback'\n"
        "with SessionLocal() as s:\n"
        "    print(s.scalar(select(func.count()).select_from(User)))\n"
    )
    env = {**os.environ, "DATABASE_URL": "postgresql://nobody:x@127.0.0.1:1/none", "JWT_SECRET": "t"}
    run = subprocess.run([sys.executable, "-c", script], cwd=config.ROOT, env=env,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip().isdigit()
