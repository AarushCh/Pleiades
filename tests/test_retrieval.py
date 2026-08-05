from __future__ import annotations

import re

import pytest


def sections(retrieval) -> set[str]:
    return {d.metadata.get("section", "") for d in retrieval.docs}


def labels(retrieval) -> set[str]:
    return {d.metadata["source_label"] for d in retrieval.docs}


def test_retrieval_returns_scored_documents(assistant):
    r = assistant.retrieve("How do I do a factory reset?", [])
    assert r.docs
    assert len(r.docs) == len(r.scores)
    assert any("Factory reset" in s for s in sections(r))


def test_keyword_search_finds_exact_product_codes(assistant):
    hits = assistant._keyword("RX-900 throughput specification", 10)
    assert any("RX-900" in d.page_content for d in hits)


def test_keyword_search_finds_ticket_ids(assistant):
    hits = assistant._keyword("TKT-10231", 10)
    assert any("TKT-10231" in d.page_content for d in hits)


def test_no_history_means_no_condensing(assistant):
    r = assistant.retrieve("What does the RX-900 cost?", [])
    assert r.condensed is False
    assert r.query == "What does the RX-900 cost?"


@pytest.mark.llm
def test_doa_policy_is_retrieved_for_natural_phrasing(assistant):
    r = assistant.retrieve("My router died 4 days after it arrived. Do I have to do triage?", [])
    assert any("Dead on arrival" in s for s in sections(r)), (
        "The DOA clause overrides the triage requirement. Without it the assistant "
        "answers from the RMA section and tells the customer to run triage, which is wrong."
    )


@pytest.mark.llm
def test_sla_credit_table_is_retrieved_for_downtime_question(assistant):
    r = assistant.retrieve("I was down for about 3 days last month. Do I get anything back?", [])
    assert any("SLA service credits" in s for s in sections(r)), (
        "Plain vector search does not rank this table in the top 12 because the customer "
        "says 'down' and the policy says 'uptime achieved'. Query expansion is what finds it."
    )
    assert r.expansions


@pytest.mark.llm
def test_condensing_preserves_detail_from_the_original_question(assistant):
    history = [("My internet is broken", "Let us check the LED colour.")]
    q = "My router died 4 days after it arrived. Do I have to do the triage steps first?"
    r = assistant.retrieve(q, history)
    assert any("Dead on arrival" in s for s in sections(r)), (
        "Condensing alone drops '4 days', which changes the correct answer. The original "
        "question must be retrieved alongside the condensed one."
    )


ABSENCE = re.compile(
    r"do(es)?\s*n[o']t\s+(have|see|contain|find|include|cover)"
    r"|not\s+(available|found|covered|in the)"
    r"|no\s+information|could\s*n[o']t\s+find|unable to"
    r"|outside (the|our) (scope|knowledge)",
    re.IGNORECASE,
)


@pytest.mark.llm
@pytest.mark.parametrize(
    "question,fabrication",
    [
        ("Who won the world cup in 2018?", "france"),
        ("What is the capital of France?", "paris"),
    ],
)
def test_out_of_scope_questions_are_refused(assistant, question, fabrication):
    answer = assistant.answer(question, remember=False)["answer"]
    assert fabrication not in answer.lower(), f"Answered from parametric memory: {answer}"
    assert ABSENCE.search(answer), f"No refusal signal: {answer}"


@pytest.mark.llm
def test_cross_document_question_pulls_manual_and_tickets(assistant):
    r = assistant.retrieve("internet light is solid orange and nothing works", [])
    assert {"RX-500/RX-900 Router Manual", "Historical Support Tickets"} <= labels(r)
