from __future__ import annotations

import argparse
import random
import re

from external import EXTERNAL, KS, answered, fetch, isolate, organisation, pct, table, wilson, write_kb

DATA = EXTERNAL / "repliqa"
URL = ("https://huggingface.co/datasets/ServiceNow/repliqa/resolve/bc880adc948fd3a70d5f8b2b3a1d1ee90d820dbd/"
       "data/repliqa_0-00000-of-00001.parquet")
NOT_FOUND = "The answer is not found in the document."
TOPICS = ("Company Policies", "Incident Report", "Small and Medium Enterprises", "Cybersecurity News")
DECLINED = re.compile(r"does(?:n't| not) cover|not covered|do(?:n't| not) have|no information|isn't in|is not in|"
                      r"(?:can't|cannot|couldn't) (?:find|confirm|answer)|pass (?:you|this) to", re.I)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def correct(answer: str, gold: str) -> bool:
    want = set(words(gold))
    return bool(want) and len(want & set(words(answer))) / len(want) >= 0.6


def load(topics: tuple[str, ...], docs: int, seed: int) -> tuple[dict[str, str], list[dict]]:
    import pandas as pd

    frame = pd.read_parquet(fetch(URL, DATA / "repliqa_0.parquet"))
    frame = frame[frame["document_topic"].isin(topics)]
    chosen = random.Random(seed).sample(sorted(frame["document_id"].unique()), docs)
    frame = frame[frame["document_id"].isin(chosen)]
    kb = {f"{d}.md": f"# {topic}: {d}\n\n{text}" for d, topic, text in
          frame[["document_id", "document_topic", "document_extracted"]].drop_duplicates("document_id").itertuples(
              index=False)}
    cases = [{"question": q, "answer": a, "file": f"{d}.md", "answerable": a != NOT_FOUND}
             for d, q, a in frame[["document_id", "question", "answer"]].itertuples(index=False)]
    return kb, cases


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RepLiQA: unseen documents, about a fifth of the questions unanswerable from them")
    parser.add_argument("--docs", type=int, default=300)
    parser.add_argument("--answers", type=int, default=0, help="also answer this many questions (uses the model)")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    isolate(DATA / "work", model=bool(args.answers))
    kb, cases = load(TOPICS, args.docs, args.seed)
    write_kb(DATA / "work" / "kb", kb)
    bot = organisation("repliqa", "Northwind")
    answerable = [c for c in cases if c["answerable"]]
    deep, hits = max(KS), [0] * len(KS)
    for case in answerable:
        found = [d.metadata["filename"] == case["file"]
                 for d in bot.retrieve(case["question"], [], top_k=deep, expand=False).docs]
        hits = [h + any(found[:k]) for h, k in zip(hits, KS, strict=True)]
    print(f"\nRepLiQA split 0, topics {', '.join(TOPICS)}: {len(kb)} documents, {len(bot.chunks)} chunks, "
          f"{len(cases)} questions ({len(cases) - len(answerable)} unanswerable)\n")
    table(["source document retrieved", *(f"@{k}" for k in KS)],
          [["answerable questions", *(pct(h, len(answerable)) for h in hits)]])
    if not args.answers:
        return

    rng, unique = random.Random(args.seed), list({c["question"]: c for c in cases}.values())
    sample = [c for want in (False, True) for c in rng.sample(
        [c for c in unique if c["answerable"] == want], args.answers // 2 if not want else args.answers - args.answers // 2)]
    replies = answered(bot, [c["question"] for c in sample], DATA / "answers.jsonl")
    tally = {"answered right": 0, "answered wrong": 0, "declined": 0,
             "declined right": 0, "made something up": 0, "unanswerable": 0}
    for case in sample:
        reply = replies[case["question"]]
        declined = reply["outcome"] == "escalated" or bool(DECLINED.search(reply["answer"]))
        if case["answerable"]:
            key = "declined" if declined else "answered right" if correct(reply["answer"], case["answer"]) \
                else "answered wrong"
            tally[key] += 1
        else:
            tally["unanswerable"] += 1
            tally["declined right" if declined else "made something up"] += 1
    n_ans, n_un = len(sample) - tally["unanswerable"], tally["unanswerable"]
    print(f"\nAnswers from {bot.backend_name} on {len(sample)} questions\n")
    table(["outcome", "share (%)", "95% interval"],
          [[name, pct(tally[key], n), wilson(tally[key], n)] for name, key, n in (
              ("answerable: answered correctly", "answered right", n_ans),
              ("answerable: answered wrongly", "answered wrong", n_ans),
              ("answerable: declined", "declined", n_ans),
              ("unanswerable: declined", "declined right", n_un),
              ("unanswerable: answered anyway", "made something up", n_un))])


if __name__ == "__main__":
    main()
