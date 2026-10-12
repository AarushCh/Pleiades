from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import random
import statistics
import tarfile
import urllib.request
import zlib

import numpy as np
from external import BITEXT, EXTERNAL, ROOT, fetch, isolate, pct, table

DATA = EXTERNAL / "abstain"
CLINC = "https://raw.githubusercontent.com/clinc/oos-eval/828f8093932c8fe6ca7936c3d2e52903b1c523de/data/"
BANKING = ("https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
           "57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data/test.csv")
MASSIVE = "https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.1.tar.gz"
ABCD = "https://raw.githubusercontent.com/asappresearch/abcd/6b8700ce67c6b37b062dd7a60abc76d7ef832a97/data/abcd_v1.1.json.gz"
LOCALES = ("en-US", "hi-IN", "bn-BD", "ta-IN", "te-IN", "kn-IN", "ml-IN", "ur-PK")
MONEY = {"banking", "credit_cards"}
SHORT = ["fiber cut in my area", "no net since morning", "can i get a refund if i change my mind?", "internet down",
         "wifi?", "bill", "refund", "help", "router broken", "hi", "hello, I need help", "talk to a human", "cancel",
         "speed test", "no signal", "slow", "mera internet nahi chal raha", "wifi kaam nahi kar raha hai",
         "bill zyada aaya hai is mahine", "net bahut slow hai yaar", "router ki light laal hai", "refund kab milega",
         "plan kaise change karu", "naa wifi pani cheyyatledu", "internet chala slow ga undi", "bill ekkuva vachindi",
         "मेरा इंटरनेट नहीं चल रहा है", "मेरा बिल ज़्यादा आया है", "నా ఇంటర్నెట్ పని చేయడం లేదు",
         "என் இணையம் வேலை செய்யவில்லை"]


def clinc() -> tuple[dict, dict]:
    data = json.loads(fetch(CLINC + "data_full.json", DATA / "clinc_full.json").read_text(encoding="utf-8"))
    domains = json.loads(fetch(CLINC + "domains.json", DATA / "clinc_domains.json").read_text(encoding="utf-8"))
    skip = {i for d in MONEY for i in domains[d]} | {"order_status"}
    other = {s: [t for t, i in data[s] if i not in skip] for s in ("train", "val", "test")}
    return data, other


def massive(locale: str) -> dict[str, list[str]]:
    folder = DATA / "massive"
    if not all((folder / f"{name}.jsonl").exists() for name in LOCALES):
        folder.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(MASSIVE, headers={"User-Agent": "pleiades-eval"})
        with urllib.request.urlopen(req, timeout=300) as r, tarfile.open(fileobj=r, mode="r|gz") as tar:
            for m in tar:
                name = m.name.rsplit("/", 1)[-1]
                if m.isfile() and name.removesuffix(".jsonl") in LOCALES:
                    (folder / name).write_bytes(tar.extractfile(m).read())
    out: dict[str, list[str]] = {}
    for line in (folder / f"{locale}.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        out.setdefault(row["partition"], []).append(row["utt"])
    return out


def bitext(name: str, rng: random.Random, train: int, test: int) -> tuple[list[str], list[str]]:
    by_intent: dict[str, list[str]] = {}
    with fetch(BITEXT[name], EXTERNAL / "bitext" / f"{name}.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_intent.setdefault(r["intent"], []).append(r["instruction"])
    held = [[q for q in qs if zlib.crc32(q.encode()) % 5 == 0] for _, qs in sorted(by_intent.items())]
    kept = [[q for q in qs if zlib.crc32(q.encode()) % 5] for _, qs in sorted(by_intent.items())]
    return ([q for qs in kept for q in rng.sample(qs, min(train, len(qs)))],
            [q for qs in held for q in rng.sample(qs, min(test, len(qs)))])


def abcd() -> dict[str, list[str]]:
    convos = json.loads(gzip.decompress(fetch(ABCD, EXTERNAL / "abcd" / "abcd_v1.1.json.gz").read_bytes()))
    return {split: [t for c in convos[split] for t in
                    [next((t for s, t in c["original"] if s == "customer" and len(t.split()) >= 5), None)] if t]
            for split in ("train", "dev", "test")}


def encoder():
    from src.embeddings import MiniLMEmbeddings, embedder_tag

    path = DATA / f"embeddings_{embedder_tag() or 'minilm'}.npz"
    cache = dict(np.load(path)) if path.exists() else {}

    def embed(texts: list[str]) -> np.ndarray:
        keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
        missing = sorted({k: t for k, t in zip(keys, texts, strict=True) if k not in cache}.items())
        for i in range(0, len(missing), 256):
            batch = missing[i:i + 256]
            for (k, _), v in zip(batch, MiniLMEmbeddings().embed_documents([t for _, t in batch]), strict=True):
                cache[k] = np.asarray(v, dtype=np.float32)
        if missing:
            np.savez(path, **cache)
        return np.stack([cache[k] for k in keys]) if keys else np.zeros((0, 384), dtype=np.float32)

    return embed


def train(x: np.ndarray, y: np.ndarray, steps: int = 3000) -> tuple[np.ndarray, float]:
    weight = np.where(y == 1, len(y) / (2 * y.sum()), len(y) / (2 * (len(y) - y.sum()))).astype(np.float32)
    w, b = np.zeros(x.shape[1], dtype=np.float32), 0.0
    for _ in range(steps):
        g = (1 / (1 + np.exp(-(x @ w + b))) - y) * weight
        w -= 2.0 * (x.T @ g / len(y) + 1e-4 * w)
        b -= 2.0 * float(g.mean())
    return w, b


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Telling support questions from off-topic ones: retrieval similarity alone, and a classifier")
    parser.add_argument("--keep", type=float, default=0.998,
                        help="share of held-out Bitext and ABCD support questions the classifier must keep")
    parser.add_argument("--ceiling", type=float, default=0.5,
                        help="never refuse a question whose best knowledge-base similarity reaches this")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    isolate()
    from src.embeddings import embedder_tag
    from src.rag import SupportAssistant

    rng = random.Random(args.seed)
    full, other = clinc()
    en = massive("en-US")
    telco_train, telco_test = bitext("telco", rng, 120, 30)
    general_train, general_test = bitext("general", rng, 120, 30)
    openers = abcd()
    cases = [c for name in ("dataset.json", "answers.json")
             for c in json.loads((ROOT / "eval" / name).read_text(encoding="utf-8"))]
    pairs = ROOT / "training" / "build" / "product" / "pairs.jsonl"
    teacher = [p["question"] for line in pairs.read_text(encoding="utf-8").splitlines()
               for p in json.loads(line)["pairs"]] if pairs.exists() else []
    with fetch(BANKING, DATA / "banking77_test.csv").open(encoding="utf-8") as f:
        banking = [r["text"] for r in csv.DictReader(f)]

    support = telco_train + general_train + rng.sample(openers["train"], 3000)
    elsewhere = ([t for t, _ in full["oos_train"]] + rng.sample(other["train"], 4000)
                 + rng.sample(en["train"], 4000))
    check_in = telco_test[:300] + general_test[:300] + rng.sample(openers["dev"], 600)
    sets = {
        "Nimbus benchmark questions": ([c["question"] for c in cases if not c.get("refuse")], True),
        "Nimbus must-refuse questions": ([c["question"] for c in cases if c.get("refuse")], False),
        "Short and code-mixed support questions, hand-written": (SHORT, True),
        "Nimbus customer questions by the teacher model": (teacher, True),
        "Bitext Telco, held out": (telco_test[300:], True),
        "Bitext customer service, held out": (general_test[300:], True),
        "ABCD customer openers, test": (openers["test"], True),
        "Banking77, another industry's support, test": (banking, True),
        "CLINC150 out-of-scope, test": ([t for t, _ in full["oos_test"]], False),
        "CLINC150 other domains, test": (rng.sample(other["test"], 1000), False),
        "MASSIVE en-US, test": (rng.sample(en["test"], 1000), False),
        **{f"MASSIVE {loc}, test": (rng.sample(massive(loc)["test"], 400), False) for loc in LOCALES[1:]},
    }

    embed = encoder()
    w, b = train(embed(support + elsewhere), np.array([1] * len(support) + [0] * len(elsewhere), dtype=np.float32))

    def p_in(texts: list[str]) -> np.ndarray:
        return 1 / (1 + np.exp(-(embed(texts) @ w + b)))

    threshold = float(np.quantile(p_in(check_in), 1 - args.keep))
    bot = SupportAssistant(fallbacks=False)
    rows = []
    for name, (texts, inside) in sets.items():
        found = bot.store._collection.query(query_embeddings=embed(texts).tolist(), n_results=1, include=["distances"])
        sims = np.array([max(0.0, 1.0 - d[0]) for d in found["distances"]])
        flagged = p_in(texts) < threshold
        both = flagged & (sims < args.ceiling)
        rows.append([name, "keep" if inside else "refuse", len(texts), f"{statistics.median(sims):.2f}",
                     pct(int(flagged.sum()), len(texts)), pct(int(both.sum()), len(texts))])

    print(f"\nEmbedder {embedder_tag() or 'all-MiniLM-L6-v2'}; classifier trained on {len(support)} support and "
          f"{len(elsewhere)} other questions; threshold {threshold:.3f} keeps {args.keep:.1%} of validation "
          f"support questions; Nimbus knowledge base {len(bot.chunks)} chunks\n")
    table(["question set", "should", "n", "median similarity", "refused by classifier (%)",
           f"refused by classifier and similarity < {args.ceiling} (%)"], rows)


if __name__ == "__main__":
    main()
