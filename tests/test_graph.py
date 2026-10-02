from __future__ import annotations

import pytest

from src.graph import ESCALATION
from src.grounding import figures
from src.rag import format_context

QUESTION = "How much does the Fibre 100 plan cost each month?"
INVENTED = "That plan is 987654321 rupees a month."


class Scripted:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.questions: list[str] = []

    def invoke(self, payload: dict) -> str:
        self.questions.append(payload["question"])
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


@pytest.fixture
def scripted(assistant, monkeypatch):
    def use(*replies: str) -> Scripted:
        model = Scripted(*replies)
        monkeypatch.setattr(assistant, "answer_chain", model)
        return model

    return use


def test_a_grounded_draft_is_answered_first_time(assistant, scripted):
    model = scripted("You can see the plan details in the catalog.")
    turn = assistant.respond(QUESTION, [])
    assert turn["outcome"] == "answered"
    assert turn["attempts"] == 1
    assert len(model.questions) == 1


def test_a_figure_taken_from_the_context_passes(assistant, scripted):
    context = format_context(assistant.retrieve(QUESTION, []).docs)
    real = sorted(figures(context), key=float)[-1]
    scripted(f"The figure in our documentation is {real}.")
    turn = assistant.respond(QUESTION, [])
    assert turn["outcome"] == "answered"
    assert turn["unsupported"] == []


def test_an_invented_figure_is_sent_back_and_corrected(assistant, scripted):
    model = scripted(INVENTED, "Please check the plan catalog for the current price.")
    turn = assistant.respond(QUESTION, [])
    assert turn["outcome"] == "answered"
    assert turn["attempts"] == 2
    assert "987654321" in model.questions[1]
    assert "987654321" not in turn["answer"]


def test_a_draft_that_keeps_inventing_figures_is_escalated(assistant, scripted):
    scripted(INVENTED)
    turn = assistant.respond(QUESTION, [])
    assert turn["outcome"] == "escalated"
    assert turn["answer"] == ESCALATION
    assert turn["unsupported"] == ["987654321"]


def test_an_empty_draft_is_escalated(assistant, scripted):
    scripted("")
    turn = assistant.respond(QUESTION, [])
    assert turn["outcome"] == "escalated"
    assert turn["attempts"] == 1


def test_a_figure_the_customer_already_gave_is_not_held_against_the_answer(assistant, scripted):
    scripted("Being without service for 987654321 seconds is a long time.")
    turn = assistant.respond("I was without service for 987654321 seconds", [])
    assert turn["outcome"] == "answered"
