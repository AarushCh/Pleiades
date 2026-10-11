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


def test_numbers_the_context_spells_out_support_digits_in_the_answer():
    context = "Refunds take seven days, twenty-three regions qualify, the third reminder is final, 1.5 million users, 2 lakh."
    answer = "Refunds take 7 days in 23 regions; the 3rd reminder is final for 1,500,000 users and 200,000 more."
    assert unsupported(answer, context) == []
    assert unsupported("It takes 8 days.", context) == ["8"]
    assert unsupported("The 100th anniversary.", "One hundred years ago today.") == []
    assert figures("seven days") == set()


def test_opening_hours_may_be_quoted_on_either_clock():
    assert unsupported("Support runs 8 am to 10 pm IST.", "Support runs 08:00 to 22:00 IST every day.") == []
    assert unsupported("The shop shuts at 21:00.", "Open 9 am to 9 pm.") == []
    assert unsupported("Support runs 8 am to 11 pm.", "Support runs 08:00 to 22:00.") == ["23"]
    assert unsupported("Open 9 am to 9 pm with 4 tills.", "Open 09:00-21:00 with five tills.") == ["4"]


def test_unsupported_figures_come_back_in_numeric_order():
    assert unsupported("Pay 300 or 25 or 1,000.", "nothing here") == ["25", "300", "1000"]
