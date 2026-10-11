from __future__ import annotations

import re

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
NOT_A_FIGURE = re.compile(r"(?im)^[ \t]*(?:[-*][ \t]+)?\d{1,2}[.)][ \t]|\bstep[ \t]+\d{1,2}\b")
UNITS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
ORDINALS = "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split()
WORDS = {w: i for i, w in enumerate(UNITS)} | {w: 10 * i for i, w in enumerate(TENS, 2)} | {
    w: i for i, w in enumerate(ORDINALS, 1)} | {"dozen": 12}
SPELLED = re.compile(rf"\b({'|'.join(TENS)})[- ]({'|'.join(UNITS[1:10])})\b|\b({'|'.join(WORDS)})\b", re.I)
SCALES = {"hundred": 100, "thousand": 1000, "lakh": 10**5, "million": 10**6, "crore": 10**7, "billion": 10**9}
HUNDREDS = re.compile(rf"\b({'|'.join(UNITS[1:10])}) hundred\b", re.I)
SCALED = re.compile(rf"(\d[\d,]*(?:\.\d+)?)\s*({'|'.join(SCALES)})\b", re.I)
CLOCK = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?m\b\.?", re.I)


def _normalise(raw: str) -> str:
    value = raw.replace(",", "")
    whole, _, frac = value.partition(".")
    frac = frac.rstrip("0")
    return f"{int(whole)}.{frac}" if frac else str(int(whole))


def _clock(m: re.Match) -> str:
    return f"{int(m[1]) % 12 + (12 if m[3].lower() == 'p' else 0):02d}:{m[2] or '00'}"


def figures(text: str) -> set[str]:
    return {_normalise(m) for m in NUMBER.findall(CLOCK.sub(_clock, NOT_A_FIGURE.sub(" ", text)))}


def spelled(text: str) -> set[str]:
    out = {str(WORDS[a.lower()] + WORDS[b.lower()]) if a else str(WORDS[w.lower()])
           for a, b, w in SPELLED.findall(text)} | {str(100 * WORDS[n.lower()]) for n in HUNDREDS.findall(text)}
    return out | {_normalise(f"{float(n.replace(',', '')) * SCALES[s.lower()]:.2f}") for n, s in SCALED.findall(text)}


def unsupported(answer: str, *grounds: str) -> list[str]:
    allowed: set[str] = set()
    for ground in grounds:
        allowed |= figures(ground) | spelled(ground)
    return sorted(figures(answer) - allowed, key=float)
