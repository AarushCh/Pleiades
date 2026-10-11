from __future__ import annotations

import re

MONTH_HOURS = 720
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "half a": 0.5, "half an": 0.5}
UNIT_HOURS = {"m": 1 / 60, "h": 1, "d": 24, "w": 168}
DURATION = re.compile(
    r"\b(?:(once|twice|times|per|every)\s+)?(\d+(?:\.\d+)?|half an?|an?|one|two|three|four|five|six|seven|"
    r"eight|nine|ten|eleven|twelve)[\s-]*(minutes?|mins?|hours?|hrs?|days?|weeks?)\b", re.I)
OUTAGE = re.compile(
    r"\b(?:down|outage|offline|disconnect\w*|interrupt\w*|not working|cut off|"
    r"(?:no|without|lost)\s+(?:the\s+)?(?:internet|connection|connectivity|service|signal|network))\b", re.I)


def downtime_hours(text: str) -> tuple[str, float] | None:
    if not OUTAGE.search(text):
        return None
    for m in DURATION.finditer(text):
        if m.group(1):
            continue
        amount = m.group(2).lower()
        value = float(WORDS.get(amount, amount if amount[0].isdigit() else 0))
        if value > 0:
            return m.group(0).strip(), value * UNIT_HOURS[m.group(3)[0].lower()]
    return None


def tables(text: str) -> list[list[list[str]]]:
    found, block = [], []
    for line in [*text.splitlines(), ""]:
        if line.strip().startswith("|"):
            block.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif block:
            found.append(block)
            block = []
    return found


def credit_rows(table: list[list[str]]) -> list[tuple[str, str]]:
    head = [c.lower() for c in table[0]]
    up = next((i for i, c in enumerate(head) if "uptime" in c), None)
    credit = next((i for i, c in enumerate(head) if "credit" in c), None)
    if up is None or credit is None:
        return []
    return [(r[up], r[credit]) for r in table[1:]
            if len(r) > max(up, credit) and not set(r[up]) <= set("-: ")]


def matches(uptime: float, band: str) -> bool | None:
    text = band.lower()
    bounds = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", band)]
    if not bounds:
        return False
    if "sla" in text:
        return None if uptime >= bounds[0] else False
    if len(bounds) >= 2:
        return bounds[0] <= uptime <= bounds[1]
    if any(w in text for w in ("below", "under", "less", "<")):
        return uptime < bounds[0]
    return uptime >= bounds[0]


def percent(value: float) -> str:
    text = f"{value:.2f}".rstrip("0")
    return f"{text}0%" if text.endswith(".") else f"{text}%"


def describe(said: str, hours: float, rows: list[tuple[str, str]]) -> str:
    uptime = round(max(0.0, 100 * (1 - hours / MONTH_HOURS)), 2)
    lead = (f"{said} of downtime is {hours:g} hours. Over a 30-day month ({MONTH_HOURS} hours) that is "
            f"{percent(uptime)} uptime.")
    for band, credit in rows:
        hit = matches(uptime, band)
        if hit:
            return f'{lead} The credit table row "{band}" applies: a {credit} credit.'
        if hit is None:
            return (f'{lead} That falls in the row "{band}", which applies only if it is below the uptime SLA '
                    f"of the customer's plan: then the credit is {credit}, otherwise no credit is due.")
    return f"{lead} No row of the credit table applies, so no credit is due."


def facts(question: str, docs) -> list[str]:
    found = downtime_hours(question)
    if found is None:
        return []
    for doc in docs:
        for table in tables(doc.page_content):
            rows = credit_rows(table)
            if rows:
                return [describe(*found, rows)]
    return []
