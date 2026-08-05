from __future__ import annotations

from functools import lru_cache

from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
from langchain_core.embeddings import Embeddings


@lru_cache(maxsize=1)
def _model() -> ONNXMiniLM_L6_V2:
    return ONNXMiniLM_L6_V2()


class MiniLMEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in _model()(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
