import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
DATA = HERE / "build" / "product"
MODELS = HERE / "build" / "models"


def rows(split: str) -> list[dict]:
    path = DATA / f"embed_{split}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def train(base: str, out: Path, epochs: int, batch: int, lr: float, seed: int) -> Path:
    from datasets import Dataset
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
        losses,
        models,
    )
    from sentence_transformers.training_args import BatchSamplers

    word = models.Transformer(base, max_seq_length=256)
    pool = models.Pooling(word.get_word_embedding_dimension(), pooling_mode="mean")
    model = SentenceTransformer(modules=[word, pool, models.Normalize()], device="cuda")
    if epochs == 0:
        model.save(str(out / "st"))
        return out / "st"
    train_rows, val_rows = rows("train"), rows("val")
    data = Dataset.from_list([{"anchor": r["query"], "positive": r["positive"]} for r in train_rows])
    val = Dataset.from_list([{"anchor": r["query"], "positive": r["positive"]} for r in val_rows]) if val_rows else None
    args = SentenceTransformerTrainingArguments(
        output_dir=str(out / "checkpoints"), num_train_epochs=epochs, per_device_train_batch_size=batch,
        learning_rate=lr, warmup_ratio=0.1, seed=seed, fp16=True, logging_steps=10, save_strategy="no",
        eval_strategy="epoch" if val else "no", batch_sampler=BatchSamplers.NO_DUPLICATES, report_to=[])
    loss = losses.MultipleNegativesRankingLoss(model)
    SentenceTransformerTrainer(model=model, args=args, train_dataset=data, eval_dataset=val, loss=loss).train()
    model.save(str(out / "st"))
    shutil.rmtree(out / "checkpoints", ignore_errors=True)
    return out / "st"


def export(st_dir: Path, out: Path, quantize: bool, base: str) -> Path:
    import torch
    from transformers import AutoModel, AutoTokenizer

    onnx_dir = out / "onnx"
    shutil.rmtree(onnx_dir, ignore_errors=True)
    onnx_dir.mkdir(parents=True)
    tokenizer = AutoTokenizer.from_pretrained(str(st_dir))
    encoder = AutoModel.from_pretrained(str(st_dir)).eval()

    class Encoder(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, input_ids, attention_mask, token_type_ids):
            return self.inner(input_ids=input_ids, attention_mask=attention_mask,
                              token_type_ids=token_type_ids).last_hidden_state

    model = Encoder(encoder).eval()
    sample = tokenizer(["a sample sentence"], return_tensors="pt", padding="max_length", max_length=16)
    names = ["input_ids", "attention_mask", "token_type_ids"]
    axes = {n: {0: "batch", 1: "sequence"} for n in [*names, "last_hidden_state"]}
    with torch.no_grad():
        torch.onnx.export(model, tuple(sample[n] for n in names), str(onnx_dir / "model.onnx"),
                          input_names=names, output_names=["last_hidden_state"], dynamic_axes=axes,
                          opset_version=17, dynamo=False)
    tokenizer.save_pretrained(str(onnx_dir))
    encoder.config.save_pretrained(str(onnx_dir))
    from huggingface_hub import hf_hub_download

    for name in ("vocab.txt", "special_tokens_map.json"):
        if not (onnx_dir / name).exists():
            shutil.copy(hf_hub_download(base, name), onnx_dir / name)
    if quantize:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        full = onnx_dir / "model.onnx"
        small = onnx_dir / "model.int8.onnx"
        quantize_dynamic(str(full), str(small), weight_type=QuantType.QInt8)
        full.unlink()
        small.rename(full)
    from src.config import EMBED_FILES

    missing = [f for f in EMBED_FILES if not (onnx_dir / f).exists()]
    if missing:
        raise SystemExit(f"Export is missing {missing}; Chroma would replace it with the stock model")
    size = sum(f.stat().st_size for f in onnx_dir.iterdir()) / 1e6
    print(f"Exported {onnx_dir} ({size:.1f} MB)")
    return onnx_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune the retrieval embedder and export it for Chroma")
    parser.add_argument("--base", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--name", default="pleiades-embed")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--quantize", action="store_true", help="int8 weights, about 4x smaller")
    parser.add_argument("--export-only", action="store_true", help="reuse the trained model in --name")
    args = parser.parse_args()

    out = MODELS / args.name
    st_dir = out / "st" if args.export_only else train(args.base, out, args.epochs, args.batch, args.lr, args.seed)
    export(st_dir, out, args.quantize, args.base)
    print(f"Use it with EMBED_MODEL_DIR={out}")


if __name__ == "__main__":
    main()
