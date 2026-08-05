from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.llm import resolve_backend


@pytest.fixture(scope="session")
def has_llm() -> bool:
    return resolve_backend() != "stub"


@pytest.fixture(scope="session")
def assistant():
    if not config.CHROMA_DIR.exists():
        pytest.skip("No vector index. Run: python -m src.ingest")
    from src.rag import SupportAssistant

    return SupportAssistant()


@pytest.fixture(autouse=True)
def _skip_llm(request, has_llm):
    if request.node.get_closest_marker("llm") and not has_llm:
        pytest.skip("No language model backend configured")
