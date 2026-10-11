from __future__ import annotations

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


def organisation(slug: str, labels: dict[str, str] | None = None, model: bool = False):
    from src import config
    from src.ingest import build_index
    from src.rag import SupportAssistant

    config.SOURCE_LABELS.update(labels or {})
    build_index(slug)
    return SupportAssistant(tenant=slug, fallbacks=model)


def best_similarity(bot, questions: list[str], batch: int = 256) -> list[float]:
    from src.embeddings import MiniLMEmbeddings

    out: list[float] = []
    for i in range(0, len(questions), batch):
        vectors = MiniLMEmbeddings().embed_documents(questions[i:i + batch])
        found = bot.store._collection.query(query_embeddings=vectors, n_results=1, include=["distances"])
        out += [max(0.0, 1.0 - d[0]) for d in found["distances"]]
    return out


def table(header: list[str], rows: list[list]) -> None:
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for row in rows:
        print("| " + " | ".join(str(c) for c in row) + " |")


def pct(hits: int, total: int) -> str:
    return f"{100 * hits / total:.1f}" if total else "-"
