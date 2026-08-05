from __future__ import annotations

import argparse
import hashlib
import shutil

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src import config
from src.embeddings import MiniLMEmbeddings

HEADERS = [("#", "doc_title"), ("##", "section"), ("###", "subsection")]


def load_documents() -> list[Document]:
    rows = _from_database()
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


def _from_database() -> list[Document]:
    try:
        from src.db import load_documents_from_db

        rows = load_documents_from_db()
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


def get_vectorstore() -> Chroma:
    return Chroma(
        collection_name=config.COLLECTION_NAME,
        embedding_function=MiniLMEmbeddings(),
        persist_directory=str(config.CHROMA_DIR),
        collection_metadata={"hnsw:space": config.DISTANCE_METRIC},
    )


def build_index(rebuild: bool = False) -> Chroma:
    if rebuild and config.CHROMA_DIR.exists():
        shutil.rmtree(config.CHROMA_DIR)
        print(f"Removed existing index at {config.CHROMA_DIR}")

    docs = load_documents()
    chunks = split_documents(docs)
    print(f"Loaded {len(docs)} documents -> {len(chunks)} chunks")

    store = get_vectorstore()
    existing = set(store.get(include=[])["ids"])
    new = [c for c in chunks if c.metadata["hash"] not in existing]

    if new:
        store.add_documents(new, ids=[c.metadata["hash"] for c in new])
        print(f"Embedded and stored {len(new)} new chunks")
    else:
        print("Index already up to date")

    print(f"Collection '{config.COLLECTION_NAME}' holds {store._collection.count()} chunks")
    return store


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the enterprise knowledge base index")
    parser.add_argument("--rebuild", action="store_true", help="wipe the index first")
    build_index(rebuild=parser.parse_args().rebuild)
