from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src import config
from src.rag import SupportAssistant

DATASET = Path(__file__).resolve().parent / "dataset.json"


def matched(retrieval, case: dict) -> bool:
    sections = {d.metadata.get("section", "") for d in retrieval.docs}
    if any(any(e in s for s in sections) for e in case.get("expected_sections", [])):
        return True
    bodies = [d.page_content for d in retrieval.docs]
    return any(any(marker in b for b in bodies) for marker in case.get("expected_contains", []))


def run_mode(bot: SupportAssistant, cases: list[dict], expand: bool, repeats: int) -> dict:
    original = config.EXPAND_THRESHOLD
    config.EXPAND_THRESHOLD = original if expand else 0.0

    rows, latencies = [], []
    try:
        for case in cases:
            hits = 0
            for _ in range(repeats):
                start = time.perf_counter()
                r = bot.retrieve(case["question"], [])
                latencies.append((time.perf_counter() - start) * 1000)
                hits += matched(r, case)
            rows.append({
                "id": case["id"],
                "hits": hits,
                "repeats": repeats,
                "note": case.get("note", ""),
            })
    finally:
        config.EXPAND_THRESHOLD = original

    recall = sum(r["hits"] for r in rows) / (len(rows) * repeats)
    return {"rows": rows, "recall": recall, "p50_ms": statistics.median(latencies)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure retrieval recall on a labelled set")
    parser.add_argument("--repeats", type=int, default=3,
                        help="runs per question; expansion is non-deterministic")
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()

    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    bot = SupportAssistant()

    print(f"Backend   {bot.backend_name}")
    print(f"Index     {len(bot.chunks)} chunks, top-{bot.top_k}, cosine")
    print(f"Dataset   {len(cases)} questions x {args.repeats} runs\n")

    baseline = run_mode(bot, cases, expand=False, repeats=args.repeats)
    hybrid = None if args.baseline_only else run_mode(bot, cases, expand=True, repeats=args.repeats)

    width = max(len(c["id"]) for c in cases)
    header = f"{'question':<{width}}  vector"
    if hybrid:
        header += "  +expansion"
    print(header)
    print("-" * len(header))

    for i, case in enumerate(cases):
        b = baseline["rows"][i]
        line = f"{case['id']:<{width}}  {b['hits']}/{b['repeats']:<5}"
        if hybrid:
            h = hybrid["rows"][i]
            mark = "  " if h["hits"] == b["hits"] else (" +" if h["hits"] > b["hits"] else " -")
            line += f" {h['hits']}/{h['repeats']}{mark}"
        print(line)

    print()
    print(f"vector only      recall {baseline['recall']:.1%}   p50 {baseline['p50_ms']:.0f}ms")
    if hybrid:
        delta = hybrid["recall"] - baseline["recall"]
        print(f"with expansion   recall {hybrid['recall']:.1%}   p50 {hybrid['p50_ms']:.0f}ms"
              f"   ({delta:+.1%})")


if __name__ == "__main__":
    main()
