import argparse
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "build" / "product"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline import OFF_TOPIC, norm, split_of, verified_pairs

GEN_SYSTEM = (
    "You write training data for the customer support assistant of an internet provider. From the passage, "
    "write {n} questions that real customers would type, each with the answer the passage supports. Write the "
    "questions the way customers actually talk: describe symptoms instead of naming policies, use everyday words "
    "instead of the document's terms, sometimes informal, sometimes with a typo, never copying a heading. Answers "
    "must be fully supported by the passage, 1 to 4 sentences, and copy every figure, price, duration, model and "
    "ticket number exactly as written. Return only a JSON array of objects with the keys question and answer."
)
REFUSAL_TEXT = ("The knowledge base does not cover that. I can pass you to a human agent who can help.")


def held_out() -> list[set[str]]:
    questions = []
    for name in ("dataset.json", "answers.json"):
        questions += [c["question"] for c in json.loads((ROOT / "eval" / name).read_text(encoding="utf-8"))]
    return [set(norm(q).split()) for q in questions]


def too_close(question: str, blocked: list[set[str]], limit: float = 0.5) -> bool:
    words = set(norm(question).split())
    return any(len(words & b) / len(words | b) >= limit for b in blocked if words | b)


def generate(bot, per_chunk: int, pause: float) -> Path:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    path = OUT / "pairs.jsonl"
    done = ({json.loads(line)["chunk"] for line in path.read_text(encoding="utf-8").splitlines()}
            if path.exists() else set())
    chain = ChatPromptTemplate.from_messages([
        ("system", GEN_SYSTEM), ("human", "Source: {label} > {section}\n\n{passage}")]) | bot.llm | StrOutputParser()
    todo = [c for c in bot.chunks if c.metadata["hash"] not in done and len(c.page_content) >= 120]
    print(f"Teacher {bot.backend_name}: {len(todo)} chunks, {per_chunk} questions each")
    with path.open("a", encoding="utf-8") as f:
        for i, c in enumerate(todo, 1):
            section = c.metadata.get("section") or c.metadata.get("doc_title") or ""
            for attempt in range(5):
                try:
                    raw = chain.invoke({"n": per_chunk, "label": c.metadata["source_label"],
                                        "section": section, "passage": c.page_content})
                    break
                except Exception as exc:
                    if "RateLimit" not in type(exc).__name__:
                        raise
                    time.sleep(20 * (attempt + 1))
            else:
                print(f"  [{i}/{len(todo)}] still rate limited, skipped")
                continue
            kept = verified_pairs(raw, c.page_content)
            f.write(json.dumps({"chunk": c.metadata["hash"], "pairs": kept}, ensure_ascii=False) + "\n")
            print(f"  [{i}/{len(todo)}] {c.metadata['source_label']} > {section[:44]}: kept {len(kept)}")
            time.sleep(pause)
    return path


def assemble(bot, refusals: float, absent: float, seed: int) -> None:
    from src import config
    from src.grounding import unsupported
    from src.rag import SYSTEM_PROMPT, format_context

    config.EXPAND_THRESHOLD = 0.0
    random.seed(seed)
    blocked = held_out()
    records = [json.loads(line) for line in (OUT / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    embed = {"train": [], "val": []}
    sft = {"train": [], "val": []}
    stats = {"pairs": 0, "held_out_skipped": 0, "gold_absent": 0, "refusals": 0}
    seen: set[str] = set()

    def chat(question, answer, docs):
        return {"messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"<context>\n{format_context(docs)}\n</context>\n<question>{question}</question>"},
            {"role": "assistant", "content": answer}]}

    for rec in records:
        chunk = bot.by_hash.get(rec["chunk"])
        if chunk is None:
            continue
        label = chunk.metadata["source_label"]
        section = chunk.metadata.get("section") or chunk.metadata.get("doc_title") or ""
        split = split_of(f"{label}|{section}")
        for pair in rec["pairs"]:
            key = norm(pair["question"])
            if too_close(pair["question"], blocked):
                stats["held_out_skipped"] += 1
                continue
            if key in seen:
                continue
            seen.add(key)
            stats["pairs"] += 1
            embed[split].append({"query": pair["question"], "positive": chunk.page_content,
                                 "chunk": chunk.metadata["hash"]})
            others = [d for d in bot.retrieve(pair["question"], []).docs
                      if d.metadata["hash"] != chunk.metadata["hash"]][:bot.top_k - 1]
            if random.random() < absent and unsupported(pair["answer"], format_context(others)):
                sft[split].append(chat(pair["question"], REFUSAL_TEXT, others))
                stats["gold_absent"] += 1
                continue
            docs = list(others)
            docs.insert(random.randrange(len(docs) + 1), chunk)
            source = f"{label} > {section}" if section else label
            sft[split].append(chat(pair["question"], f"{pair['answer']}\n\nSources: {source}", docs))

    for _ in range(int(stats["pairs"] * refusals)):
        question = random.choice(OFF_TOPIC)
        sft[split_of(question)].append(chat(question, REFUSAL_TEXT, bot.retrieve(question, []).docs))
        stats["refusals"] += 1

    for split in ("train", "val"):
        random.shuffle(sft[split])
        for name, rows in (("embed", embed[split]), ("sft", sft[split])):
            with (OUT / f"{name}_{split}.jsonl").open("w", encoding="utf-8") as f:
                f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    sizes = {f"{n}_{s}": len(d[s]) for n, d in (("embed", embed), ("sft", sft)) for s in ("train", "val")}
    print(json.dumps({**stats, **sizes}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Teacher-generated, verified training data for the support models")
    parser.add_argument("--per-chunk", type=int, default=6)
    parser.add_argument("--pause", type=float, default=6.0)
    parser.add_argument("--refusals", type=float, default=0.12, help="off-topic refusals per grounded pair")
    parser.add_argument("--absent", type=float, default=0.1, help="share of pairs trained with the passage removed")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()

    from src.rag import SupportAssistant

    OUT.mkdir(parents=True, exist_ok=True)
    bot = SupportAssistant(fallbacks=False)
    if not args.assemble_only:
        generate(bot, args.per_chunk, args.pause)
    assemble(bot, args.refusals, args.absent, args.seed)


if __name__ == "__main__":
    main()
