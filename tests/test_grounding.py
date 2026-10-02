from __future__ import annotations

from src.grounding import figures, unsupported

CONTEXT = "The Fibre 100 plan costs ₹1,499 a month. Uptime below 99.5% earns a 50% credit."


def test_a_figure_from_the_context_is_supported():
    assert unsupported("Fibre 100 is ₹1,499 per month.", CONTEXT) == []


def test_an_invented_figure_is_caught():
    assert unsupported("Fibre 100 is ₹1,299 per month.", CONTEXT) == ["1299"]


def test_formatting_differences_do_not_matter():
    assert figures("₹1,499.00 and 99.50% and 050") == {"1499", "99.5", "50"}


def test_a_figure_the_customer_gave_is_supported():
    answer = "Being down for 3 days puts you below 99.5%, so you get a 50% credit."
    assert unsupported(answer, CONTEXT, "I was down for 3 days") == []


def test_list_numbering_and_step_labels_are_not_figures():
    answer = "1. Unplug the router.\n2) Wait.\n- 3. Plug it in.\nStep 4 is optional."
    assert figures(answer) == set()


def test_a_derived_figure_is_not_supported():
    assert unsupported("Three days down is about 90.4% uptime.", CONTEXT) == ["90.4"]


def test_unsupported_figures_come_back_in_numeric_order():
    assert unsupported("Pay 300 or 25 or 1,000.", "nothing here") == ["25", "300", "1000"]
