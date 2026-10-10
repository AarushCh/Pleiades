from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableLambda

from src import config, llm
from src.llm import STUB_LABEL, ExtractiveStubLLM, first_answering, get_llm_with_fallbacks


@pytest.fixture
def groq_only(monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "auto")
    monkeypatch.setattr(config, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(config, "LLAMA_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(llm, "ollama_available", lambda: False)


def test_every_groq_model_becomes_its_own_fallback(groq_only, monkeypatch):
    monkeypatch.setattr(config, "GROQ_MODEL", "qwen/qwen3.8-27b")
    monkeypatch.setattr(config, "GROQ_FALLBACK_MODELS", ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"])
    _, name, spares = get_llm_with_fallbacks()
    assert name == "Groq · qwen/qwen3.8-27b"
    assert spares == ["Groq · openai/gpt-oss-120b", STUB_LABEL]


def test_reasoning_models_are_told_not_to_spend_the_answer_budget_thinking():
    assert llm._reasoning("openai/gpt-oss-120b") == {"reasoning_effort": "low"}
    assert llm._reasoning("qwen/qwen3.8-27b") == {"reasoning_effort": "none"}
    assert llm._reasoning("some-plain-model") == {}


def test_a_hosted_model_is_preferred_over_a_local_one(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(config, "LLAMA_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(llm, "ollama_available", lambda: True)
    assert llm.available_backends() == ["groq", "ollama"]


def _model(reply: str | None):
    def call(_prompt):
        if reply is None:
            raise RuntimeError("model retired")
        return reply

    return RunnableLambda(call)


def test_health_reports_the_first_model_that_actually_answers():
    chain = _model(None).with_fallbacks([_model("OK"), ExtractiveStubLLM()])
    answering, failures = first_answering(chain, ["Retired", "Working", STUB_LABEL])
    assert answering == "Working"
    assert failures == ["Retired: RuntimeError"]


def test_health_admits_when_nothing_answers():
    chain = _model(None).with_fallbacks([_model(None), ExtractiveStubLLM()])
    answering, failures = first_answering(chain, ["A", "B", STUB_LABEL])
    assert answering == STUB_LABEL
    assert len(failures) == 2
