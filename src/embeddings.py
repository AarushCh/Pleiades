from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
from langchain_core.embeddings import Embeddings

from src import config


@lru_cache(maxsize=1)
def _model() -> ONNXMiniLM_L6_V2:
    model = ONNXMiniLM_L6_V2()
    if config.EMBED_MODEL_DIR:
        folder = Path(config.EMBED_MODEL_DIR) / model.EXTRACTED_FOLDER_NAME
        missing = [f for f in config.EMBED_FILES if not (folder / f).exists()]
        if missing:
            raise RuntimeError(f"EMBED_MODEL_DIR is missing {missing} in {folder}")
        model.DOWNLOAD_PATH = Path(config.EMBED_MODEL_DIR)
    return model


def embedder_tag() -> str:
    return Path(config.EMBED_MODEL_DIR).name if config.EMBED_MODEL_DIR else ""


class MiniLMEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in _model()(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
