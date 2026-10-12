from __future__ import annotations

import argparse
import json
import shutil
import tarfile
import urllib.request

from external import EXTERNAL, KS, isolate, organisation, pct, table, write_kb

DATA = EXTERNAL / "techqa"
URL = ("https://huggingface.co/datasets/PrimeQA/TechQA/resolve/60437bc79ab217679682217598a3693cab78365b/"
       "TechQA.tar.gz")
FILES = ("dev_Q_A.json", "training_dev_technotes.json")


def fetch() -> None:
    if all((DATA / f).exists() for f in FILES):
        return
    DATA.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "pleiades-eval"})
    with urllib.request.urlopen(req, timeout=300) as r, tarfile.open(fileobj=r, mode="r|gz") as tar:
        for m in tar:
            name = m.name.rsplit("/", 1)[-1]
            if m.isfile() and name in FILES:
                with tar.extractfile(m) as src, (DATA / name).open("wb") as dst:
                    shutil.copyfileobj(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TechQA: real IBM support-forum questions; is the technote that answers them retrieved?")
    parser.add_argument("--questions", type=int, default=160, help="answerable dev questions to use (max 160)")
    args = parser.parse_args()

    fetch()
    isolate(DATA / "work")
    asked = [q for q in json.loads((DATA / "dev_Q_A.json").read_text(encoding="utf-8"))
             if q["ANSWERABLE"] == "Y"][:args.questions]
    notes = json.loads((DATA / "training_dev_technotes.json").read_text(encoding="utf-8"))
    wanted = {d for q in asked for d in q["DOC_IDS"] if d in notes}
    write_kb(DATA / "work" / "kb", {f"{d}.md": f"# {notes[d]['title']}\n\n{notes[d]['text']}" for d in sorted(wanted)})
    del notes
    bot = organisation("techqa", "IBM Support")
    deep, hits = max(KS), [0] * len(KS)
    for q in asked:
        found = [d.metadata["filename"] == f"{q['DOCUMENT']}.md" for d in bot.retrieve(
            f"{q['QUESTION_TITLE']}\n{q['QUESTION_TEXT']}", [], top_k=deep, expand=False).docs]
        hits = [h + any(found[:k]) for h, k in zip(hits, KS, strict=True)]
    print(f"\nTechQA dev: {len(asked)} answerable questions, {len(wanted)} candidate technotes pooled into one "
          f"knowledge base, {len(bot.chunks)} chunks\n")
    table(["technote that answers it", *(f"@{k}" for k in KS)], [["retrieved", *(pct(h, len(asked)) for h in hits)]])


if __name__ == "__main__":
    main()
