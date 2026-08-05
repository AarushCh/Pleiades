from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src import config
from src.ingest import get_vectorstore
from src.llm import get_llm_with_fallbacks

SYSTEM_PROMPT = (
    "You are the Nimbus Networks support assistant. Answer only from <context>.\n"
    "If <context> does not answer the question, reply with exactly one sentence saying the "
    "knowledge base does not cover it, then offer to pass the customer to a human agent. "
    "Do not offer to answer from general knowledge and do not speculate. Never invent "
    "prices, timelines or policy.\n"
    "Start with the answer itself. No greetings, no 'I'm happy to help'.\n"
    "Quote exact figures, amounts and timelines from the context rather than pointing the "
    "customer at a document. If the context has the numbers to work it out, work it out.\n"
    "Numbered steps only for procedures; use a compact table to compare things, otherwise short "
    "prose. Adopt the customer's wording. Never tell them their term is wrong: if they say "
    "orange and the manual says amber, just say orange.\n"
    "End with a Sources line citing the labels you actually used; omit that line entirely if "
    "you could not answer. Under 180 words, warm and direct, no filler openers."
)

ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "<context>\n{context}\n</context>\n{history}<question>{question}</question>"),
])

CONDENSE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "Rewrite the follow-up as a standalone search query. Output the query only."),
    ("human", "{history}Follow-up: {question}"),
])

EXPAND_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You turn customer questions into search queries against an internal knowledge base.\n"
     "These are the sections that exist:\n{sections}\n\n"
     "Pick the sections most likely to answer the question and write one search query for "
     "each, phrased in that section's own vocabulary. Keep concrete details from the "
     "question — timeframes, model numbers, amounts, LED colours — because they decide "
     "which section applies.\n"
     "Output at most 3 queries, one per line, no numbering, no other text."),
    ("human", "{question}"),
])

REFERENTIAL = re.compile(
    r"\b(it|its|that|this|those|these|they|them|their|he|she|his|her|"
    r"one|other|another|same|instead|then|also|too)\b",
    re.IGNORECASE,
)


def format_context(docs: list[Document]) -> str:
    blocks, seen = [], set()
    for d in docs:
        body = d.page_content.strip()
        if body in seen:
            continue
        seen.add(body)
        label = d.metadata.get("source_label", d.metadata.get("filename", "unknown"))
        section = d.metadata.get("section") or d.metadata.get("doc_title") or ""
        head = f"[Source: {label}" + (f" > {section}]" if section else "]")
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)


def format_history(history: list[tuple[str, str]]) -> str:
    if not history:
        return ""
    lines = []
    for q, a in history[-config.HISTORY_TURNS:]:
        reply = a[:config.HISTORY_REPLY_CHARS]
        if len(a) > config.HISTORY_REPLY_CHARS:
            reply += "..."
        lines.append(f"Q: {q}\nA: {reply}")
    return "History:\n" + "\n".join(lines) + "\n\n"


def est_tokens(text: str) -> int:
    return len(text) // 4


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class Retrieval:
    docs: list[Document]
    scores: list[float | None]
    query: str
    condensed: bool
    expansions: list[str]


@dataclass
class SupportAssistant:
    top_k: int = config.TOP_K
    history: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        from rank_bm25 import BM25Okapi

        from src.ingest import load_documents, split_documents

        self.llm, self.backend_name, self.fallbacks = get_llm_with_fallbacks()
        self.last_error: str | None = None
        self.store = get_vectorstore()
        self.answer_chain = ANSWER_PROMPT | self.llm | StrOutputParser()
        self.condense_chain = CONDENSE_PROMPT | self.llm | StrOutputParser()
        self.expand_chain = EXPAND_PROMPT | self.llm | StrOutputParser()

        self.chunks = split_documents(load_documents())
        self.by_hash = {c.metadata["hash"]: c for c in self.chunks}
        self.bm25 = BM25Okapi([tokenize(c.page_content) for c in self.chunks])

        seen: set[str] = set()
        headings: list[str] = []
        for c in self.chunks:
            section = c.metadata.get("section") or c.metadata.get("doc_title") or ""
            line = f"{c.metadata['source_label']} > {section}" if section else c.metadata["source_label"]
            if line not in seen:
                seen.add(line)
                headings.append(line)
        self.sections = "\n".join(headings)

    @property
    def has_llm(self) -> bool:
        return not self.backend_name.startswith("Extractive")

    def _needs_condensing(self, question: str, history: list[tuple[str, str]]) -> bool:
        if not history or not self.has_llm:
            return False
        return bool(REFERENTIAL.search(question)) or len(question.split()) <= 4

    def _vector(self, query: str, k: int) -> list[tuple[Document, float]]:
        hits = self.store.similarity_search_with_score(query, k=k)
        return [(d, max(0.0, 1.0 - dist)) for d, dist in hits]

    def _keyword(self, query: str, k: int) -> list[Document]:
        scores = self.bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        return [self.chunks[i] for i in order if scores[i] > 0]

    def _expand(self, query: str) -> list[str]:
        try:
            raw = self.expand_chain.invoke({"question": query, "sections": self.sections})
            self.last_error = None
        except Exception as exc:
            self.last_error = f"Query expansion unavailable: {type(exc).__name__}"
            return []
        lines = [ln.strip(" -*\t") for ln in raw.splitlines() if ln.strip()]
        return [ln for ln in lines if 3 < len(ln) < 160][:3]

    def retrieve(self, question: str, history: list[tuple[str, str]] | None = None) -> Retrieval:
        history = self.history if history is None else history
        condensed = self._needs_condensing(question, history)
        query = question
        if condensed:
            query = self.condense_chain.invoke({
                "history": format_history(history),
                "question": question,
            }).strip() or question

        pool = self.top_k * 2
        primary = self._vector(question, pool)
        base = [primary] + ([self._vector(query, pool)] if condensed else [])
        best = max((h[0][1] for h in base if h), default=0.0)

        expansions: list[str] = []
        if self.has_llm and best < config.EXPAND_THRESHOLD:
            expansions = self._expand(query)

        sims: dict[str, float] = {}
        for hits in base + [self._vector(q, pool) for q in expansions]:
            for doc, sim in hits:
                h = doc.metadata["hash"]
                sims[h] = max(sims.get(h, 0.0), sim)

        fused = {h: s for h, s in sims.items() if s >= config.MIN_RELEVANCE}
        for h in (d.metadata["hash"] for d in self._keyword(question, pool)):
            fused[h] = fused.get(h, 0.0) + config.KEYWORD_BONUS

        anchors = [
            doc.metadata["hash"]
            for doc, sim in primary[:min(config.ANCHORS, self.top_k)]
            if sim >= config.MIN_RELEVANCE
        ]
        top = list(dict.fromkeys(anchors))
        for h in sorted(fused, key=lambda h: -fused[h]):
            if len(top) >= self.top_k:
                break
            if h not in top:
                top.append(h)
        if not top and primary:
            top = [primary[0][0].metadata["hash"]]

        docs = [self.by_hash[h] for h in top if h in self.by_hash]
        scores = [sims.get(h) for h in top if h in self.by_hash]
        return Retrieval(docs, scores, query, condensed, expansions)

    def _payload(self, question: str, r: Retrieval,
                 history: list[tuple[str, str]] | None = None) -> dict:
        return {
            "context": format_context(r.docs),
            "history": format_history(self.history if history is None else history),
            "question": question,
        }

    def stream(self, question: str, r: Retrieval,
               history: list[tuple[str, str]] | None = None) -> Iterator[str]:
        yield from self.answer_chain.stream(self._payload(question, r, history))

    def prompt_tokens(self, question: str, r: Retrieval,
                      history: list[tuple[str, str]] | None = None) -> int:
        p = self._payload(question, r, history)
        return est_tokens(SYSTEM_PROMPT + p["context"] + p["history"] + question)

    def remember(self, question: str, answer: str) -> None:
        self.history.append((question, answer))

    def sources(self, r: Retrieval) -> list[dict]:
        seen, out = set(), []
        for doc, score in zip(r.docs, r.scores):
            label = doc.metadata.get("source_label", doc.metadata.get("filename", "unknown"))
            section = doc.metadata.get("section") or doc.metadata.get("doc_title") or ""
            if (label, section) in seen:
                continue
            seen.add((label, section))
            out.append({
                "label": label,
                "section": section,
                "score": score,
                "retriever": "vector" if score else "keyword",
                "excerpt": doc.page_content.strip()[:400],
            })
        return out

    def answer(self, question: str, remember: bool = True) -> dict:
        r = self.retrieve(question)
        payload = self._payload(question, r)
        text = self.answer_chain.invoke(payload).strip()
        if remember:
            self.remember(question, text)
        return {
            "answer": text,
            "sources": self.sources(r),
            "search_query": r.query,
            "condensed": r.condensed,
            "expansions": r.expansions,
            "backend": self.backend_name,
            "prompt_tokens": est_tokens(SYSTEM_PROMPT + payload["context"]
                                        + payload["history"] + question),
            "doc_count": len(r.docs),
        }

    def reset(self) -> None:
        self.history.clear()
