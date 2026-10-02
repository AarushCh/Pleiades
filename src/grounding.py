from __future__ import annotations

import re

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
NOT_A_FIGURE = re.compile(r"(?im)^[ \t]*(?:[-*][ \t]+)?\d{1,2}[.)][ \t]|\bstep[ \t]+\d{1,2}\b")


def _normalise(raw: str) -> str:
    value = raw.replace(",", "")
    whole, _, frac = value.partition(".")
    frac = frac.rstrip("0")
    return f"{int(whole)}.{frac}" if frac else str(int(whole))


def figures(text: str) -> set[str]:
    return {_normalise(m) for m in NUMBER.findall(NOT_A_FIGURE.sub(" ", text))}


def unsupported(answer: str, *grounds: str) -> list[str]:
    allowed: set[str] = set()
    for ground in grounds:
        allowed |= figures(ground)
    return sorted(figures(answer) - allowed, key=float)
