from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.language_models.llms import LLM

from src import config


class ExtractiveStubLLM(LLM):
    @property
    def _llm_type(self) -> str:
        return "extractive-stub"

    def _call(self, prompt: str, stop: Any = None, **kwargs: Any) -> str:
        if "<context>" not in prompt:
            return ""
        context = re.sub(r"^\[Source:.*$", "", _between(prompt, "<context>", "</context>"), flags=re.M)
        question = _between(prompt, "<question>", "</question>")
        if not context.strip():
            return "I don't have anything in the knowledge base that covers that."

        keywords = {w for w in re.findall(r"[a-z0-9]{4,}", question.lower())}
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", context) if len(s.strip()) > 30]

        scored = sorted(
            ((len(keywords & set(re.findall(r"[a-z0-9]{4,}", s.lower()))), -i, s)
             for i, s in enumerate(sentences)),
            reverse=True,
        )
        best = [s for score, _, s in scored[:4] if score > 0]
        if not best:
            return "I don't have anything in the knowledge base that covers that."

        return ("[extractive answer - language model unavailable]\n\n"
                + "\n\n".join(f"- {s}" for s in best))


def _between(text: str, start: str, end: str) -> str:
    b = text.rfind(end)
    a = text.rfind(start, 0, b if b != -1 else len(text))
    return text[a + len(start):b] if a != -1 and b > a else ""


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=1.5) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def available_backends() -> list[str]:
    order = []
    if ollama_available():
        order.append("ollama")
    if config.LLAMA_API_BASE and config.LLAMA_API_KEY:
        order.append("llama-api")
    if config.GROQ_API_KEY:
        order.append("groq")
    if config.OPENROUTER_API_KEY:
        order.append("openrouter")
    return order


def resolve_backend() -> str:
    if config.LLM_BACKEND != "auto":
        return config.LLM_BACKEND
    return next(iter(available_backends()), "stub")


def get_llm_with_fallbacks() -> tuple[BaseLanguageModel, str, list[str]]:
    chosen = resolve_backend()
    primary, name = build_llm(chosen)
    if chosen == "stub":
        return primary, name, []

    spares, models = [], []
    for backend in available_backends():
        if backend == chosen:
            continue
        try:
            models.append(build_llm(backend)[0])
            spares.append(backend)
        except Exception:
            continue
    models.append(ExtractiveStubLLM())
    return primary.with_fallbacks(models), name, spares + ["stub"]


def get_llm() -> tuple[BaseLanguageModel, str]:
    return build_llm(resolve_backend())


def build_llm(backend: str) -> tuple[BaseLanguageModel, str]:
    if backend == "ollama":
        from langchain_ollama import ChatOllama
        return (
            ChatOllama(
                model=config.OLLAMA_MODEL,
                base_url=config.OLLAMA_BASE_URL,
                temperature=config.TEMPERATURE,
                num_predict=config.MAX_TOKENS,
            ),
            f"Ollama · {config.OLLAMA_MODEL} (local)",
        )

    if backend == "llama-api":
        if not (config.LLAMA_API_BASE and config.LLAMA_API_KEY):
            raise SystemExit("LLM_BACKEND=llama-api needs LLAMA_API_BASE and LLAMA_API_KEY")
        from urllib.parse import urlparse
        from langchain_openai import ChatOpenAI
        return (
            ChatOpenAI(
                model=config.LLAMA_API_MODEL,
                api_key=config.LLAMA_API_KEY,
                base_url=config.LLAMA_API_BASE,
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
                timeout=config.LLM_TIMEOUT,
                max_retries=1,
            ),
            f"{urlparse(config.LLAMA_API_BASE).netloc} · {config.LLAMA_API_MODEL}",
        )

    if backend == "groq":
        if not config.GROQ_API_KEY:
            raise SystemExit("LLM_BACKEND=groq but GROQ_API_KEY is not set")
        from langchain_groq import ChatGroq
        return (
            ChatGroq(
                model=config.GROQ_MODEL,
                api_key=config.GROQ_API_KEY,
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
                timeout=config.LLM_TIMEOUT,
                max_retries=1,
            ),
            f"Groq · {config.GROQ_MODEL}",
        )

    if backend == "openrouter":
        if not config.OPENROUTER_API_KEY:
            raise SystemExit("LLM_BACKEND=openrouter but OPENROUTER_API_KEY is not set")
        from langchain_openai import ChatOpenAI
        return (
            ChatOpenAI(
                model=config.OPENROUTER_MODEL,
                api_key=config.OPENROUTER_API_KEY,
                base_url=config.OPENROUTER_BASE_URL,
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
                timeout=config.LLM_TIMEOUT,
                max_retries=1,
            ),
            f"OpenRouter · {config.OPENROUTER_MODEL}",
        )

    return ExtractiveStubLLM(), "Extractive stub (no LLM configured)"


def _list_models(key: str, url: str) -> list[str]:
    import json
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return sorted(m["id"] for m in json.load(r).get("data", []))


def _main() -> None:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    backend = resolve_backend()
    print(f"Resolved backend: {backend}")
    llm, name = get_llm()
    print(f"Using: {name}")

    try:
        reply = llm.invoke("Reply with exactly: OK")
        print("Test call:", getattr(reply, "content", reply))
    except Exception as exc:
        print(f"\nTest call FAILED: {exc}\n")
        endpoints = {
            "groq": (config.GROQ_API_KEY, "https://api.groq.com/openai/v1/models", "GROQ_MODEL"),
            "llama-api": (config.LLAMA_API_KEY, f"{config.LLAMA_API_BASE}/models", "LLAMA_API_MODEL"),
            "openrouter": (config.OPENROUTER_API_KEY,
                           f"{config.OPENROUTER_BASE_URL}/models", "OPENROUTER_MODEL"),
        }
        key, url, var = endpoints.get(backend, (None, None, None))
        if key:
            print("Models reachable with your key:")
            for m in _list_models(key, url):
                print(f"  - {m}")
            print(f"\nSet the one you want as {var} in .env")


if __name__ == "__main__":
    _main()
