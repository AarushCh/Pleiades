from __future__ import annotations

import argparse
import csv
import os
import random
import statistics
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "eval" / "external" / "bitext"
URL = ("https://huggingface.co/datasets/bitext/Bitext-telco-llm-chatbot-training-dataset/resolve/"
       "eacc593a96d75ec6da0887f081ff0dfc442fccab/bitext-telco-llm-chatbot-training-dataset.csv")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def rows() -> list[dict]:
    path = DATA / "telco.csv"
    if not path.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL, path)
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="How well the knowledge base covers real telecom support intents (Bitext Telco)")
    parser.add_argument("--per-intent", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    os.environ.update(GROQ_API_KEY="", OPENROUTER_API_KEY="", LLAMA_API_KEY="", OLLAMA_BASE_URL="http://127.0.0.1:9",
                      KB_FROM_DB="0")
    sys.path.insert(0, str(ROOT))
    from src.rag import SupportAssistant

    bot = SupportAssistant(fallbacks=False)
    by_intent: dict[tuple[str, str], list[str]] = {}
    for r in rows():
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

    print(f"Knowledge base: {len(bot.chunks)} chunks; {args.per_intent} Bitext phrasings per intent\n")
    print("| intent | category | median best similarity | most retrieved section | share |")
    print("|---|---|---|---|---|")
    for median, category, intent, top, share in sorted(report):
        print(f"| {intent} | {category} | {median:.2f} | {top} | {share:.0%} |")


if __name__ == "__main__":
    main()
