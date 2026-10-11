from __future__ import annotations

import argparse
import gzip
import json

from external import EXTERNAL, KS, fetch, isolate, organisation, table, write_kb

DATA = EXTERNAL / "abcd"
BASE = "https://raw.githubusercontent.com/asappresearch/abcd/6b8700ce67c6b37b062dd7a60abc76d7ef832a97/data/"


def slug(title: str) -> str:
    return title.lower().replace("-", "_").replace(" ", "_")


def guidelines() -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    guide = json.loads(fetch(BASE + "guidelines.json", DATA / "guidelines.json").read_text(encoding="utf-8"))
    ontology = json.loads(fetch(BASE + "ontology.json", DATA / "ontology.json").read_text(encoding="utf-8"))
    docs, where = {}, {}
    for flow, body in guide.items():
        lines = [f"# {flow}", "", f"Covers {body['description']}."]
        for key, (name, sub) in zip(ontology["intents"]["subflows"][slug(flow)], body["subflows"].items(),
                                    strict=True):
            where[key] = (flow, name)
            lines += ["", f"## {name}", "", *sub["instructions"][:1], ""]
            for i, action in enumerate(sub["actions"], 1):
                button = f"**{action['button']}**: " if action["button"] != "N/A" else ""
                lines.append(f"{i}. {button}{action['text']}")
                lines += [f"   - {s}" for s in action["subtext"]]
            lines += ["", *sub["instructions"][1:]]
        docs[f"{slug(flow)}.md"] = "\n".join(lines).strip() + "\n"
    return docs, where


def cases(split: str, where: dict, turns: int) -> list[dict]:
    convos = json.loads(gzip.decompress(fetch(BASE + "abcd_v1.1.json.gz", DATA / "abcd_v1.1.json.gz").read_bytes()))
    out = []
    for c in convos[split]:
        said = [t for s, t in c["original"] if s == "customer" and len(t.split()) >= 3][:turns]
        sub = c["scenario"]["subflow"]
        flow, name = where.get(sub) or where[sub.split("_")[0]]
        out.append({"question": " ".join(said), "flow": flow, "subflow": name})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ABCD: does a customer's opening message reach the agent guideline for their request?")
    parser.add_argument("--split", default="test", choices=["train", "dev", "test"])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    isolate(DATA / "work")
    docs, where = guidelines()
    write_kb(DATA / "work" / "kb", docs)
    bot = organisation("abcd", {name: f"AcmeBrands guidelines: {name[:-3].replace('_', ' ').title()}" for name in docs})
    deep = max(KS)
    rows = []
    for turns in (1, 2):
        todo = cases(args.split, where, turns)[: args.limit or None]
        flow, sub = [0] * len(KS), [0] * len(KS)
        for case in todo:
            docs_found = bot.retrieve(case["question"], [], top_k=deep, expand=False).docs
            flows = [d.metadata.get("doc_title") == case["flow"] for d in docs_found]
            subs = [f and d.metadata.get("section") == case["subflow"] for d, f in zip(docs_found, flows, strict=True)]
            flow = [n + any(flows[:k]) for n, k in zip(flow, KS, strict=True)]
            sub = [n + any(subs[:k]) for n, k in zip(sub, KS, strict=True)]
        label = "first customer message" if turns == 1 else "first two customer messages"
        rows += [[f"right flow, {label}", *(f"{100 * n / len(todo):.1f}" for n in flow)],
                 [f"right subflow, {label}", *(f"{100 * n / len(todo):.1f}" for n in sub)]]
    print(f"\nABCD {args.split}: {len(todo)} conversations, {len(where)} subflows in {len(docs)} guideline documents, "
          f"{len(bot.chunks)} chunks\n")
    table(["guideline retrieved", *(f"@{k}" for k in KS)], rows)


if __name__ == "__main__":
    main()
