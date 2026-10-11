from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "eval" / "external" / "doc2dial"
URL = "https://doc2dial.github.io/file/doc2dial_v1.0.1.zip"
MULTI = "https://doc2dial.github.io/multidoc2dial/file/multidoc2dial.zip"
FILES = ("doc2dial_doc.json", "doc2dial_dial_validation.json", "doc2dial_dial_test.json")
CONTEXTS = ("follow-up alone", "with the previous question", "with the last exchange")
KS = (1, 3, 6, 10)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fetch() -> None:
    if all((DATA / f).exists() for f in FILES):
        return
    DATA.mkdir(parents=True, exist_ok=True)
    archive = DATA / Path(URL).name
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    with zipfile.ZipFile(archive) as z:
        for name in FILES:
            (DATA / name).write_bytes(z.read(name))


def corpus(kb: Path) -> dict[str, dict]:
    kb.mkdir(parents=True, exist_ok=True)
    docs = json.loads((DATA / "doc2dial_doc.json").read_text(encoding="utf-8"))["doc_data"]
    by_id = {}
    for domain, items in sorted(docs.items()):
        for i, (doc_id, doc) in enumerate(sorted(items.items())):
            name = f"{domain}-{i:03d}.md"
            path = kb / name
            body = f"# {doc['title']}\n\n{doc['doc_text']}"
            if not path.exists() or path.read_text(encoding="utf-8") != body:
                path.write_text(body, encoding="utf-8")
            by_id[doc_id] = {"file": name, "spans": doc["spans"]}
    return by_id


def cases(by_id: dict, split: str) -> list[dict]:
    dials = json.loads((DATA / f"doc2dial_dial_{split}.json").read_text(encoding="utf-8"))["dial_data"]
    out = []
    for domain in dials.values():
        for doc_id, items in domain.items():
            for dial in items:
                turn = dial["turns"][0]
                if turn["role"] == "user" and turn["references"]:
                    spans = by_id[doc_id]["spans"]
                    out.append({"question": turn["utterance"], "file": by_id[doc_id]["file"],
                                "spans": [spans[r["sp_id"]]["text_sp"] for r in turn["references"]]})
    return out


def follow_ups(by_id: dict, split: str) -> list[dict]:
    archive = DATA.parent / "multidoc2dial" / "multidoc2dial.zip"
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MULTI, archive)
    with zipfile.ZipFile(archive) as z:
        dials = json.loads(z.read(f"multidoc2dial/multidoc2dial_dial_{split}.json"))["dial_data"]
    out = []
    for domain in dials.values():
        for dial in domain:
            turns = dial["turns"]
            for i in range(1, len(turns) - 1):
                user, agent = turns[i], turns[i + 1]
                refs = [r for r in agent["references"] if r["doc_id"] in by_id]
                if user["role"] != "user" or agent["role"] != "agent" or not refs:
                    continue
                asked = [t["utterance"] for t in turns[:i] if t["role"] == "user"]
                said = [t["utterance"] for t in turns[:i]]
                docs = {by_id[r["doc_id"]]["file"] for r in refs}
                pairs = [(a["utterance"], b["utterance"]) for a, b in zip(turns[:i], turns[1:i], strict=False)
                         if a["role"] == "user" and b["role"] == "agent"]
                out.append({"question": user["utterance"], "history": pairs,
                            "questions": {"follow-up alone": user["utterance"],
                                          "with the previous question": " ".join(asked[-1:] + [user["utterance"]]),
                                          "with the last exchange": " ".join(said[-2:] + [user["utterance"]])},
                            "files": docs,
                            "spans": [by_id[r["doc_id"]]["spans"][r["id_sp"]]["text_sp"] for r in refs]})
    return out


def norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def holds(body: str, span: str) -> bool:
    words = norm(span).split()
    if len(words) <= 8:
        return " ".join(words) in body
    mid = len(words) // 2
    return any(" ".join(w) in body for w in (words[:8], words[mid - 4:mid + 4], words[-8:]))


def score(ranked: list, case: dict) -> dict[str, list[bool]]:
    doc = [c.metadata["filename"] in case.get("files", {case.get("file")}) for c in ranked]
    span = [d and any(holds(norm(c.page_content), s) for s in case["spans"]) for c, d in zip(ranked, doc, strict=True)]
    return {"document": [any(doc[:k]) for k in KS], "passage": [any(span[:k]) for k in KS]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval recall on doc2dial's human-written, span-grounded questions")
    parser.add_argument("--split", default="validation", choices=["validation", "test"])
    parser.add_argument("--embedder", default=None,
                        help="EMBED_MODEL_DIR to use; 'default' for all-MiniLM-L6-v2; omit for the .env setting")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--follow-ups", action="store_true",
                        help="MultiDoc2Dial follow-up questions instead of doc2dial first turns")
    args = parser.parse_args()

    fetch()
    work = DATA / "work"
    by_id = corpus(work / "kb")
    os.environ.update(KB_DIR=str(work / "kb"), KB_FROM_DB="0", CHROMA_DIR=str(work / "chroma"),
                      GROQ_API_KEY="", OPENROUTER_API_KEY="", LLAMA_API_KEY="",
                      OLLAMA_BASE_URL="http://127.0.0.1:9")
    if args.embedder is not None:
        os.environ["EMBED_MODEL_DIR"] = "" if args.embedder == "default" else args.embedder
    sys.path.insert(0, str(ROOT))

    from src.embeddings import embedder_tag
    from src.ingest import build_index
    from src.rag import SupportAssistant

    build_index("doc2dial")
    bot = SupportAssistant(tenant="doc2dial", fallbacks=False)
    deep = max(KS)
    name = embedder_tag() or "all-MiniLM-L6-v2"
    if args.follow_ups:
        todo = follow_ups(by_id, args.split)[: args.limit or None]
        print(f"MultiDoc2Dial {args.split}: {len(todo)} follow-up questions, {len(by_id)} documents, "
              f"{len(bot.chunks)} chunks, embedder {name}; target is the passage the agent's reply uses\n")
        print("| hybrid query | " + " | ".join(f"{kind} @{k}" for kind in ("passage", "document") for k in KS) + " |")
        print("|---|" + "---|" * (2 * len(KS)))
        for context in [*CONTEXTS, "Pleiades with the conversation history"]:
            totals = {"document": [0] * len(KS), "passage": [0] * len(KS)}
            for case in todo:
                found = (bot.retrieve(case["question"], case["history"], top_k=deep) if context not in CONTEXTS
                         else bot.retrieve(case["questions"][context], [], top_k=deep)).docs
                for kind, hits in score(found, case).items():
                    totals[kind] = [t + h for t, h in zip(totals[kind], hits, strict=True)]
            cells = [f"{100 * h / len(todo):.1f}" for kind in ("passage", "document") for h in totals[kind]]
            print(f"| {context} | " + " | ".join(cells) + " |")
        return
    todo = cases(by_id, args.split)[: args.limit or None]
    modes = {
        "vector": lambda q: [d for d, _ in bot._vector(q, deep)],
        "keyword": lambda q: bot._keyword(q, deep),
        "hybrid": lambda q: bot.retrieve(q, [], top_k=deep).docs,
    }
    totals = {m: {"document": [0] * len(KS), "passage": [0] * len(KS)} for m in modes}
    for case in todo:
        for mode, run in modes.items():
            for kind, hits in score(run(case["question"]), case).items():
                totals[mode][kind] = [t + h for t, h in zip(totals[mode][kind], hits, strict=True)]

    print(f"doc2dial {args.split}: {len(todo)} first user turns, {len(by_id)} documents, "
          f"{len(bot.chunks)} chunks, embedder {name}\n")
    print("| mode | " + " | ".join(f"{kind} @{k}" for kind in ("passage", "document") for k in KS) + " |")
    print("|---|" + "---|" * (2 * len(KS)))
    for mode, kinds in totals.items():
        cells = [f"{100 * h / len(todo):.1f}" for kind in ("passage", "document") for h in kinds[kind]]
        print(f"| {mode} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
