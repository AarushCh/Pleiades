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


def test_the_extractive_fallback_quotes_whole_sentences_not_headings():
    context = (
        "[Source: Help Centre > Is there a cancellation fee?]\n## Is there a cancellation fee?\n"
        "Monthly plans have no cancellation fee, early exit fee or early termination charge, because there\n"
        "is no contract lock-in: cancellation takes effect at the end of the current billing period."
    )
    answer = ExtractiveStubLLM().invoke(f"<context>{context}</context><question>Is there an early exit fee?</question>")
    assert "because there is no contract lock-in" in answer
    assert "##" not in answer

    table = ("| Product | Price | Notes |\n|---|---|---|\n"
             "| RX-500 router | ₹3,500 | Wi-Fi 5, included free with Lite/Plus lease |\n"
             "| RX-900 router | ₹6,900 | Wi-Fi 6, included free with Max lease |")
    answer = ExtractiveStubLLM().invoke(f"<context>{table}</context><question>What does the RX-900 cost?</question>")
    assert "₹6,900" in answer

    mixed = f"{table}\nPrices include GST and are charged once at purchase."
    answer = ExtractiveStubLLM().invoke(f"<context>{mixed}</context><question>Is GST charged on top?</question>")
    assert "- Prices include GST" in answer

    faq = ("[Source: Billing FAQ > How do I get a GST invoice?]\n## How do I get a GST invoice?\n"
           "Add your GSTIN under Account → Billing Profile before the 25th of the month.\n\n"
           "[Source: Help Centre > Where can I see or download my invoices?]\n"
           "Account → Billing → Invoices lists every invoice with its PDF, generated monthly.")
    answer = ExtractiveStubLLM().invoke(f"<context>{faq}</context><question>How do I get a GST invoice?</question>")
    assert answer.split("\n\n")[1].startswith("- Add your GSTIN")
