from types import SimpleNamespace

import pytest

from src import config, sla

CATALOG = SimpleNamespace(page_content=(config.DATA_DIR / "product_catalog.md").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("question", "expected"), [
    ("I was down for about 3 days last month. Do I get anything back?", ("90.0%", '"90.0% – 94.99%"', "50%")),
    ("Internet was out, no connection for 10 hours", ("98.61%", '"95.0% – 98.99%"', "25%")),
    ("we had an outage of 2 weeks", ("53.33%", '"Below 90.0%"', "100%")),
    ("my line went down for 90 minutes", ("99.79%", "below the uptime SLA", "10%")),
    ("connection dropped, offline for half a day", ("98.33%", "25%")),
])
def test_credit_band(question, expected):
    [fact] = sla.facts(question, [CATALOG])
    for part in expected:
        assert part in fact


@pytest.mark.parametrize("question", [
    "Can I return the router within 21 days?",
    "my wifi is down twice a day",
    "How long is the warranty, 2 years?",
])
def test_no_calculation(question):
    assert sla.facts(question, [CATALOG]) == []


def test_needs_the_credit_table():
    other = SimpleNamespace(page_content="| Plan | Uptime SLA |\n|---|---|\n| Lite | 99.0% |")
    assert sla.facts("down for 3 days", [other]) == []
