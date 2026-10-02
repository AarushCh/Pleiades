from __future__ import annotations

import sys
import time

from src.rag import SupportAssistant

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

DEMO_QUESTIONS = [
    "My internet light is solid orange and I have no connection. What do I do?",
    "My router died 4 days after it arrived. Do I have to do the triage steps first?",
    "What is the difference between the Plus and Max plans?",
    "I was down for about 3 days last month. Do I get anything back?",
    "Who won the world cup in 2018?",
]

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def ask(bot: SupportAssistant, question: str) -> None:
    print(f"\n{BOLD}Customer:{RESET} {question}\n")
    start = time.perf_counter()
    turn = bot.respond(question)
    r, answer = turn["retrieval"], turn["answer"]
    print(answer)
    bot.remember(question, answer)
    total = time.perf_counter() - start

    print()
    if r.condensed:
        print(f"{DIM}  condensed: {r.query}{RESET}")
    for e in r.expansions:
        print(f"{DIM}  expanded:  {e}{RESET}")
    for s in bot.sources(r):
        loc = f" > {s['section']}" if s["section"] else ""
        tag = f"{s['score']:.2f}" if s["score"] else " kw "
        print(f"{DIM}  [{tag}] {s['label']}{loc}{RESET}")
    checked = f"{turn['outcome']} after {turn['attempts']} draft(s)"
    if turn.get("unsupported"):
        checked += f", unsupported: {', '.join(turn['unsupported'])}"
    print(f"{DIM}  {checked} | total {total:.1f}s{RESET}\n")


def main() -> None:
    args = sys.argv[1:]
    bot = SupportAssistant()
    print(f"\n{BOLD}Nimbus Support Assistant{RESET}")
    print(f"{DIM}generation: {bot.backend_name}")
    print(f"retrieval:  ChromaDB · all-MiniLM-L6-v2 · top-{bot.top_k}{RESET}")
    print("-" * 72)

    if "--demo" in args:
        for q in DEMO_QUESTIONS:
            ask(bot, q)
            print("-" * 72)
        return

    if args:
        ask(bot, " ".join(args))
        return

    print("Ask a question, 'reset' to clear history, Ctrl-C to quit.")
    while True:
        try:
            q = input(f"{BOLD}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return
        if not q:
            continue
        if q.lower() in {"reset", "clear"}:
            bot.reset()
            print("History cleared.\n")
            continue
        ask(bot, q)


if __name__ == "__main__":
    main()
