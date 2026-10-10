import argparse
import json
import re
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


def held_out() -> list[set[str]]:
    questions = []
    for name in ("dataset.json", "answers.json"):
        questions += [c["question"] for c in json.loads((ROOT / "eval" / name).read_text(encoding="utf-8"))]
    return [set(norm(q).split()) for q in questions]


def too_close(question: str, blocked: list[set[str]], limit: float = 0.5) -> bool:
    words = set(norm(question).split())
    return any(len(words & b) / len(words | b) >= limit for b in blocked if words | b)


def lines(name: str) -> list[dict]:
    path = OUT / name
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def questions(bot) -> list[dict]:
    blocked, seen, out = held_out(), set(), []
    for rec in lines("pairs.jsonl"):
        chunk = bot.by_hash.get(rec["chunk"])
        if chunk is None:
            continue
        section = chunk.metadata.get("section") or chunk.metadata.get("doc_title") or ""
        for pair in rec["pairs"]:
            key = norm(pair["question"])
            if key in seen or too_close(pair["question"], blocked):
                continue
            seen.add(key)
            out.append({"question": pair["question"], "chunk": chunk,
                        "split": split_of(f"{chunk.metadata['source_label']}|{section}")})
    return out


def generate(bot, per_chunk: int, pause: float) -> None:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    done = {r["chunk"] for r in lines("pairs.jsonl")}
    chain = ChatPromptTemplate.from_messages([
        ("system", GEN_SYSTEM), ("human", "Source: {label} > {section}\n\n{passage}")]) | bot.llm | StrOutputParser()
    todo = [c for c in bot.chunks if c.metadata["hash"] not in done and len(c.page_content) >= 120]
    print(f"Teacher {bot.backend_name}: {len(todo)} chunks, {per_chunk} questions each")
    with (OUT / "pairs.jsonl").open("a", encoding="utf-8") as f:
        for i, c in enumerate(todo, 1):
            section = c.metadata.get("section") or c.metadata.get("doc_title") or ""
            raw = patient(lambda c=c, s=section: chain.invoke({
                "n": per_chunk, "label": c.metadata["source_label"], "section": s, "passage": c.page_content}))
            kept = verified_pairs(raw, c.page_content)
            f.write(json.dumps({"chunk": c.metadata["hash"], "pairs": kept}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  [{i}/{len(todo)}] {c.metadata['source_label']} > {section[:44]}: kept {len(kept)}")
            time.sleep(pause)


def wait_hint(message: str) -> float:
    found = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", message)
    if not found:
        return 30.0
    hours, minutes, seconds = found.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds)


def patient(call, bot=None):
    for _ in range(8):
        if bot is not None:
            bot.last_error = None
        try:
            result = call()
            if bot is None or not (bot.last_error and "RateLimit" in bot.last_error):
                return result
            message = bot.last_error
        except Exception as exc:
            if "RateLimit" not in type(exc).__name__:
                raise
            message = str(exc)
        wait = wait_hint(message)
        if "per day" in message and wait > 600:
            raise SystemExit(f"The teacher's free daily token cap is used up; run again in {wait / 3600:.1f} h, "
                             "and it resumes where it stopped")
        time.sleep(wait + 2)
    raise RuntimeError("Still rate limited after eight attempts")


def distill(bot, pause: float) -> None:
    from src.rag import SupportAssistant

    done = {r["question"] for r in lines("distilled.jsonl")}
    todo = [q["question"] for q in questions(bot)] + OFF_TOPIC
    todo = [q for q in todo if q not in done]
    print(f"Teacher {bot.backend_name}: {len(todo)} questions through the production pipeline")
    with (OUT / "distilled.jsonl").open("a", encoding="utf-8") as f:
        for i, question in enumerate(todo, 1):
            expansions = patient(lambda q=question: SupportAssistant._expand(bot, q), bot)
            bot._expand = lambda _query, e=expansions: e
            try:
                turn = patient(lambda q=question: bot.respond(q, []))
            finally:
                del bot._expand
            f.write(json.dumps({
                "question": question, "expansions": expansions, "answer": turn["answer"],
                "outcome": turn["outcome"], "attempts": turn["attempts"],
                "context": [d.metadata["hash"] for d in turn["retrieval"].docs]}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  [{i}/{len(todo)}] {turn['outcome']} drafts={turn['attempts']} expansions={len(expansions)}")
            time.sleep(pause)


def assemble_embed(bot) -> None:
    rows = {"train": [], "val": []}
    for q in questions(bot):
        rows[q["split"]].append({"query": q["question"], "positive": q["chunk"].page_content,
                                 "chunk": q["chunk"].metadata["hash"]})
    for split, data in rows.items():
        with (OUT / f"embed_{split}.jsonl").open("w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in data)
    print({f"embed_{s}": len(d) for s, d in rows.items()})


def assemble_sft(bot) -> None:
    from src.rag import ANSWER_PROMPT, EXPAND_PROMPT, format_context, format_history

    role = {"system": "system", "human": "user"}
    split_by = {q["question"]: q["split"] for q in questions(bot)}
    rows, stats = {"train": [], "val": []}, {"answers": 0, "expansions": 0, "dropped": 0}

    def sample(prompt_messages, reply):
        return {"messages": [{"role": role[m.type], "content": m.content} for m in prompt_messages]
                + [{"role": "assistant", "content": reply}]}

    for rec in lines("distilled.jsonl"):
        split = split_by.get(rec["question"], split_of(rec["question"]))
        if rec["expansions"]:
            rows[split].append(sample(EXPAND_PROMPT.format_messages(question=rec["question"], sections=bot.sections),
                                      "\n".join(rec["expansions"])))
            stats["expansions"] += 1
        docs = [bot.by_hash[h] for h in rec["context"] if h in bot.by_hash]
        if rec["outcome"] != "answered" or rec["attempts"] != 1 or len(docs) != len(rec["context"]):
            stats["dropped"] += 1
            continue
        payload = {"context": format_context(docs), "history": format_history([]), "question": rec["question"]}
        rows[split].append(sample(ANSWER_PROMPT.format_messages(**payload), rec["answer"]))
        stats["answers"] += 1
    for split, data in rows.items():
        with (OUT / f"sft_{split}.jsonl").open("w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in data)
    print({**stats, **{f"sft_{s}": len(d) for s, d in rows.items()}})


def main() -> None:
    parser = argparse.ArgumentParser(description="Teacher-generated, verified training data for the support models")
    parser.add_argument("--per-chunk", type=int, default=6)
    parser.add_argument("--pause", type=float, default=6.0)
    parser.add_argument("--distill", action="store_true",
                        help="run the teacher through the production pipeline for the answering model's data")
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()

    from src.rag import SupportAssistant

    OUT.mkdir(parents=True, exist_ok=True)
    bot = SupportAssistant(fallbacks=False)
    if not args.assemble_only:
        generate(bot, args.per_chunk, args.pause)
        if args.distill:
            distill(bot, args.pause)
    assemble_embed(bot)
    assemble_sft(bot)


if __name__ == "__main__":
    main()
