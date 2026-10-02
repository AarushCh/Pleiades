from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.grounding import unsupported
from src.rag import Retrieval, format_context, format_history

MAX_ATTEMPTS = 2
ESCALATION = (
    "I couldn't confirm every figure in that answer against our documentation, so I'd rather "
    "not guess. A support agent can pick this up with you."
)


class Turn(TypedDict, total=False):
    question: str
    history: list[tuple[str, str]]
    retrieval: Retrieval
    draft: str
    unsupported: list[str]
    attempts: int
    answer: str
    outcome: str


def build_graph(bot):
    def retrieve(turn: Turn) -> Turn:
        return {"retrieval": bot.retrieve(turn["question"], turn.get("history", [])), "attempts": 0}

    def generate(turn: Turn) -> Turn:
        question = turn["question"]
        if turn.get("unsupported"):
            question += (
                "\n\nUse only figures that appear in the context. These do not: "
                + ", ".join(turn["unsupported"]) + "."
            )
        payload = bot._payload(question, turn["retrieval"], turn.get("history", []))
        return {"draft": bot.answer_chain.invoke(payload).strip(), "attempts": turn["attempts"] + 1}

    def verify(turn: Turn) -> Turn:
        grounds = (
            format_context(turn["retrieval"].docs),
            turn["question"],
            format_history(turn.get("history", [])),
        )
        return {"unsupported": unsupported(turn["draft"], *grounds)}

    def finish(turn: Turn) -> Turn:
        return {"answer": turn["draft"], "outcome": "answered"}

    def escalate(turn: Turn) -> Turn:
        return {"answer": ESCALATION, "outcome": "escalated"}

    def route(turn: Turn) -> str:
        if not turn["draft"]:
            return "escalate"
        if not turn["unsupported"]:
            return "finish"
        return "generate" if turn["attempts"] < MAX_ATTEMPTS else "escalate"

    graph = StateGraph(Turn)
    for name, step in (("retrieve", retrieve), ("generate", generate), ("verify", verify),
                       ("finish", finish), ("escalate", escalate)):
        graph.add_node(name, step)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges("verify", route, ["finish", "generate", "escalate"])
    graph.add_edge("finish", END)
    graph.add_edge("escalate", END)
    return graph.compile()
