from __future__ import annotations

import argparse
import hashlib

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src import config
from src.embeddings import MiniLMEmbeddings, embedder_tag

HEADERS = [("#", "doc_title"), ("##", "section"), ("###", "subsection")]


def collection_for(tenant: str | None = None) -> str:
    slug = (tenant or config.DEFAULT_TENANT).strip().lower().replace("-", "_")
    tag = embedder_tag().replace("-", "_")
    return f"{config.COLLECTION_NAME}_{slug}" + (f"_{tag}" if tag else "")


def load_documents(tenant: str | None = None) -> list[Document]:
    rows = _from_database(tenant) if config.KB_FROM_DB else []
    if rows:
        return rows

    paths = sorted(config.DATA_DIR.glob("**/*.md"))
    if not paths:
        raise SystemExit(f"No documents in the database and no .md files in {config.DATA_DIR}")
    return [
        Document(
            page_content=p.read_text(encoding="utf-8"),
            metadata={
                "source": str(p),
                "filename": p.name,
                "source_label": config.SOURCE_LABELS.get(p.name, p.name),
            },
        )
        for p in paths
    ]


def _from_database(tenant: str | None = None) -> list[Document]:
    try:
        from src.db import load_documents_from_db

        rows = load_documents_from_db(tenant)
    except Exception:
        return []

    return [
        Document(
            page_content=body,
            metadata={"source": f"db://documents/{filename}",
                      "filename": filename,
                      "source_label": label},
        )
        for filename, label, body in rows
    ]


def split_documents(docs: list[Document]) -> list[Document]:
    header_splitter = MarkdownHeaderTextSplitter(HEADERS, strip_headers=False)
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    chunks: list[Document] = []
    for doc in docs:
        for section in header_splitter.split_text(doc.page_content):
            section.metadata = {**doc.metadata, **section.metadata}
            chunks.extend(size_splitter.split_documents([section]))

    for i, c in enumerate(chunks):
        c.metadata["chunk_id"] = i
        c.metadata["hash"] = hashlib.sha256(
            (c.metadata["filename"] + c.page_content).encode("utf-8")
        ).hexdigest()[:16]
    return chunks


def get_vectorstore(tenant: str | None = None) -> Chroma:
    return Chroma(
        collection_name=collection_for(tenant),
        embedding_function=MiniLMEmbeddings(),
        persist_directory=str(config.CHROMA_DIR),
        collection_metadata={"hnsw:space": config.DISTANCE_METRIC},
    )


def build_index(tenant: str | None = None, rebuild: bool = False) -> Chroma:
    name = collection_for(tenant)
    if rebuild:
        get_vectorstore(tenant).delete_collection()
        print(f"Removed collection '{name}'")

    docs = load_documents(tenant)
    chunks = split_documents(docs)
    print(f"Loaded {len(docs)} documents -> {len(chunks)} chunks")

    store = get_vectorstore(tenant)
    existing = set(store.get(include=[])["ids"])
    stale = existing - {c.metadata["hash"] for c in chunks}
    new = [c for c in chunks if c.metadata["hash"] not in existing]

    if stale:
        store.delete(ids=sorted(stale))
        print(f"Removed {len(stale)} chunks whose documents changed")
    if new:
        store.add_documents(new, ids=[c.metadata["hash"] for c in new])
        print(f"Embedded and stored {len(new)} new chunks")
    if not stale and not new:
        print("Index already up to date")

    print(f"Collection '{name}' holds {store._collection.count()} chunks")
    return store


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the enterprise knowledge base index")
    parser.add_argument("--rebuild", action="store_true", help="wipe the index first")
    parser.add_argument("--tenant", default=None, help="tenant slug (default: the default tenant)")
    args = parser.parse_args()
    build_index(tenant=args.tenant, rebuild=args.rebuild)
