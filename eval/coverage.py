from __future__ import annotations

import argparse
import csv
import random
import statistics

from external import BITEXT, EXTERNAL, fetch, isolate


def rows(name: str) -> list[dict]:
    with fetch(BITEXT[name], EXTERNAL / "bitext" / f"{name}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="How well the knowledge base covers real customer-support intents (Bitext)")
    parser.add_argument("--per-intent", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--set", default="telco", choices=sorted(BITEXT),
                        help="telco: 26 telecom intents; general: 27 cross-industry customer-service intents")
    args = parser.parse_args()

    isolate()
    from src.rag import SupportAssistant

    bot = SupportAssistant(fallbacks=False)
    by_intent: dict[tuple[str, str], list[str]] = {}
    for r in rows(args.set):
        by_intent.setdefault((r["category"], r["intent"]), []).append(r["instruction"])

    rng = random.Random(args.seed)
    report = []
    for (category, intent), questions in sorted(by_intent.items()):
        sample = rng.sample(questions, min(args.per_intent, len(questions)))
        best, sections = [], {}
        for q in sample:
            [(doc, sim)] = bot._vector(q, 1)
            best.append(sim)
            key = f"{doc.metadata['source_label']} > {doc.metadata.get('section') or doc.metadata.get('doc_title', '')}"
            sections[key] = sections.get(key, 0) + 1
        top = max(sections, key=sections.get)
        report.append((statistics.median(best), category, intent, top, sections[top] / len(sample)))

    print(f"Knowledge base: {len(bot.chunks)} chunks; {args.per_intent} Bitext {args.set} phrasings per intent\n")
    print("| intent | category | median best similarity | most retrieved section | share |")
    print("|---|---|---|---|---|")
    for median, category, intent, top, share in sorted(report):
        print(f"| {intent} | {category} | {median:.2f} | {top} | {share:.0%} |")


if __name__ == "__main__":
    main()
