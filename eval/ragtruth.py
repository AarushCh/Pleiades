from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from external import EXTERNAL, fetch, isolate, pct, table

DATA = EXTERNAL / "ragtruth"
BASE = "https://raw.githubusercontent.com/ParticleMedia/RAGTruth/c103204b9ce28d6bbad859304bf30de72b8ed8fe/dataset/"


def load(name: str) -> list[dict]:
    text = fetch(BASE + name, DATA / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def ground(source: dict) -> str:
    info = source["source_info"]
    return source.get("prompt") or (info if isinstance(info, str) else json.dumps(info, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="RAGTruth: does the figure check catch hallucinated numbers?")
    parser.add_argument("--split", default="test", choices=["train", "test"])
    parser.add_argument("--examples", type=int, default=0, help="show this many clean answers that were flagged")
    args = parser.parse_args()

    isolate()
    from src.grounding import figures, unsupported

    sources = {s["source_id"]: s for s in load("source_info.jsonl")}
    stats: dict[str, Counter] = defaultdict(Counter)
    wrong: list[tuple[str, list[str], str]] = []
    for r in load("response.jsonl"):
        if r["split"] != args.split:
            continue
        source = sources[r["source_id"]]
        flagged = unsupported(r["response"], ground(source))
        wrong_figures = set().union(*(figures(label["text"]) for label in r["labels"]))
        numeric = bool(wrong_figures)
        for kind in (source["task_type"], "all"):
            s = stats[kind]
            s.update(n=1, clean=not r["labels"], numeric=numeric, flagged=bool(flagged),
                     caught=bool(wrong_figures & set(flagged)), false_alarm=bool(flagged) and not r["labels"],
                     right=bool(flagged) and bool(r["labels"]))
        if flagged and not r["labels"]:
            wrong.append((source["task_type"], flagged, r["response"]))

    print(f"RAGTruth {args.split} split: answers by six models, hallucinated spans labelled by people\n")
    table(["task", "answers", "with a hallucinated figure", "caught", "clean answers flagged",
           "flags that were right"],
          [[kind, s["n"], s["numeric"], pct(s["caught"], s["numeric"]), pct(s["false_alarm"], s["clean"]),
            pct(s["right"], s["flagged"])] for kind, s in sorted(stats.items())])
    for kind, figs, text in wrong[:args.examples]:
        print(f"\n[{kind}] unsupported {figs}: {' '.join(text.split())[:300]}")


if __name__ == "__main__":
    main()
