from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTERNAL = ROOT / "eval" / "external"
BITEXT = {
    "telco": ("https://huggingface.co/datasets/bitext/Bitext-telco-llm-chatbot-training-dataset/resolve/"
              "eacc593a96d75ec6da0887f081ff0dfc442fccab/bitext-telco-llm-chatbot-training-dataset.csv"),
    "general": ("https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset/"
                "resolve/430d1a89bd93bd1fa23c16f29dd53e73f0087443/"
                "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"),
}
NO_MODEL = {"GROQ_API_KEY": "", "OPENROUTER_API_KEY": "", "LLAMA_API_KEY": "",
            "OLLAMA_BASE_URL": "http://127.0.0.1:9"}
KS = (1, 3, 6, 10)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "pleiades-eval"})
        with urllib.request.urlopen(req, timeout=300) as r, part.open("wb") as f:
            shutil.copyfileobj(r, f)
        part.replace(dest)
    return dest


def isolate(work: Path | None = None, model: bool = False) -> None:
    env = {"KB_FROM_DB": "0", **({} if model else NO_MODEL)}
    if work:
        env |= {"KB_DIR": str(work / "kb"), "CHROMA_DIR": str(work / "chroma")}
    os.environ.update(env)
    sys.path.insert(0, str(ROOT))


def write_kb(folder: Path, docs: dict[str, str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in docs.items():
        path = folder / name
        if not path.exists() or path.read_text(encoding="utf-8") != body:
            path.write_text(body, encoding="utf-8")
    for path in folder.glob("*.md"):
        if path.name not in docs:
            path.unlink()


def organisation(slug: str, name: str, labels: dict[str, str] | None = None):
    from src import config
    from src.ingest import build_index
    from src.rag import SupportAssistant

    config.SOURCE_LABELS.update(labels or {})
    build_index(slug)
    return SupportAssistant(tenant=slug, fallbacks=False, organisation=name)


def answered(bot, questions: list[str], path: Path) -> dict[str, dict]:
    sys.path.insert(0, str(ROOT / "training"))
    from product_data import patient

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    done = {r["question"]: r for r in rows if r["model"] == bot.backend_name}
    todo = [q for q in dict.fromkeys(questions) if q not in done]
    print(f"Answering {len(todo)} questions with {bot.backend_name} ({len(done)} already in {path.name})", flush=True)
    with path.open("a", encoding="utf-8") as f:
        for i, question in enumerate(todo, 1):
            reply = patient(lambda q=question: bot.answer(q, remember=False), bot)
            done[question] = {"model": bot.backend_name, "question": question, "outcome": reply["outcome"],
                              "answer": reply["answer"], "expansions": reply["expansions"]}
            f.write(json.dumps(done[question], ensure_ascii=False) + "\n")
            f.flush()
            print(f"  [{i}/{len(todo)}] {reply['outcome']}", flush=True)
    return done


def wilson(hits: int, total: int, z: float = 1.96) -> str:
    if not total:
        return "-"
    p, d = hits / total, 1 + z * z / total
    centre, half = (p + z * z / (2 * total)) / d, z * (p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5 / d
    return f"{100 * (centre - half):.0f}-{100 * (centre + half):.0f}"


def table(header: list[str], rows: list[list]) -> None:
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for row in rows:
        print("| " + " | ".join(str(c) for c in row) + " |")


def pct(hits: int, total: int) -> str:
    return f"{100 * hits / total:.1f}" if total else "-"
