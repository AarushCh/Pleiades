from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.rag import SupportAssistant

CASES = Path(__file__).resolve().parent / "answers.json"
DASHES = re.compile(r"[‐-―−]")
SPACES = re.compile(r"[   \s]+")
PERCENT = re.compile(r"(\d) %")
REFUSAL = re.compile(
    r"do(es)?\s*n[o']t\s+(have|see|contain|find|include|cover)"
    r"|not\s+(available|found|covered|in the)"
    r"|no\s+information|could\s*n[o']t\s+find|unable to"
    r"|outside (the|our) (scope|knowledge)",
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    return PERCENT.sub(r"\1%", SPACES.sub(" ", DASHES.sub("-", text))).lower()


def correct(case: dict, answer: str) -> bool:
    text = normalise(answer)
    if any(bad in text for bad in case.get("must_not", [])):
        return False
    if case.get("refuse"):
        return bool(REFUSAL.search(text))
    return all(any(alt in text for alt in group) for group in case["must"])


def turn(bot: SupportAssistant, question: str, waits: list[float]) -> dict:
    for attempt in range(6):
        bot.last_error = None
        try:
            result = bot.respond(question, [])
            if not (bot.last_error and "RateLimit" in bot.last_error):
                return result
        except Exception as exc:
            if "RateLimit" not in type(exc).__name__ and "429" not in str(exc):
                raise
        pause = 15 * (attempt + 1)
        waits.append(pause)
        time.sleep(pause)
    raise RuntimeError(f"Still rate limited after retries: {question}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score full answers against facts from the documents")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--pause", type=float, default=0.0, help="seconds between turns")
    parser.add_argument("--out", type=Path, help="write per-turn results as JSON")
    args = parser.parse_args()

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    bot = SupportAssistant(fallbacks=False)
    print(f"Model     {bot.backend_name}")
    print(f"Cases     {len(cases)} x {args.repeats}\n")

    rows, waits = [], []
    for case in cases:
        for _ in range(args.repeats):
            start, waited = time.perf_counter(), sum(waits)
            result = turn(bot, case["question"], waits)
            seconds = time.perf_counter() - start - (sum(waits) - waited)
            ok = result["outcome"] == "answered" and correct(case, result["answer"])
            rows.append({
                "id": case["id"], "ok": ok, "outcome": result["outcome"],
                "attempts": result["attempts"], "unsupported": result.get("unsupported", []),
                "seconds": round(seconds, 2), "answer": result["answer"],
            })
            mark = "ok " if ok else "XX "
            extra = f" unsupported={result['unsupported']}" if result.get("unsupported") else ""
            print(f"{mark} {case['id']:15} {result['outcome']:9} drafts={result['attempts']} "
                  f"{seconds:5.2f}s{extra}")
            if args.pause:
                time.sleep(args.pause)

    n = len(rows)
    secs = sorted(r["seconds"] for r in rows)
    summary = {
        "model": bot.backend_name,
        "correct": sum(r["ok"] for r in rows) / n,
        "escalated": sum(r["outcome"] == "escalated" for r in rows) / n,
        "redrafted": sum(r["attempts"] > 1 for r in rows) / n,
        "p50_s": statistics.median(secs),
        "p95_s": secs[min(n - 1, round(0.95 * (n - 1)))],
        "rate_limit_waits": len(waits),
    }
    print(f"\ncorrect {summary['correct']:.1%}   escalated {summary['escalated']:.1%}   "
          f"redrafted {summary['redrafted']:.1%}   p50 {summary['p50_s']:.2f}s   p95 {summary['p95_s']:.2f}s")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False),
                            encoding="utf-8")


if __name__ == "__main__":
    main()
