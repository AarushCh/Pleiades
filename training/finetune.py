import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "build" / "product"
MODELS = HERE / "build" / "models"


def encode(tokenizer, path: Path, max_len: int) -> tuple[list[dict], int]:
    rows, dropped = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        messages = json.loads(line)["messages"]
        prompt = tokenizer.apply_chat_template(messages[:-1], add_generation_prompt=True, tokenize=False)
        full = tokenizer.apply_chat_template(messages, tokenize=False)
        if not full.startswith(prompt):
            raise SystemExit("The chat template does not extend the prompt; masking the prompt would be wrong")
        head = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        ids = tokenizer(full, add_special_tokens=False)["input_ids"]
        if ids[:len(head)] != head:
            raise SystemExit("Prompt and full sample tokenise differently at the boundary")
        if len(ids) > max_len:
            dropped += 1
            continue
        rows.append({"input_ids": ids, "attention_mask": [1] * len(ids),
                     "labels": [-100] * len(head) + ids[len(head):]})
    return rows, dropped


def train(a) -> Path:
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    out = MODELS / a.name
    tokenizer = AutoTokenizer.from_pretrained(a.base)
    train_rows, dropped = encode(tokenizer, DATA / "sft_train.jsonl", a.max_len)
    val_rows, _ = encode(tokenizer, DATA / "sft_val.jsonl", a.max_len)
    print(f"{len(train_rows)} train, {len(val_rows)} val samples; {dropped} longer than {a.max_len} tokens dropped")

    model = AutoModelForCausalLM.from_pretrained(
        a.base, dtype=torch.bfloat16, device_map={"": 0},
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_compute_dtype=torch.bfloat16,
                                               bnb_4bit_use_double_quant=True))
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, bias="none",
                                             task_type="CAUSAL_LM", target_modules="all-linear"))
    model.print_trainable_parameters()
    class AnswerOnlyTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels = inputs.pop("labels")
            if labels.size(0) != 1:
                raise ValueError("The answer-only loss assumes one sample per batch")
            answer = int(labels.ne(-100).sum())
            out = model(**inputs, logits_to_keep=answer + 1)
            logits = out.logits[:, :-1].float()
            loss = torch.nn.functional.cross_entropy(
                logits.reshape(-1, logits.size(-1)), labels[:, -answer:].reshape(-1),
                ignore_index=-100, reduction="sum") / (num_items_in_batch or answer)
            return (loss, out) if return_outputs else loss

    trainer = AnswerOnlyTrainer(
        model=model, train_dataset=Dataset.from_list(train_rows),
        eval_dataset=Dataset.from_list(val_rows) if val_rows else None,
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
        args=TrainingArguments(
            output_dir=str(out / "checkpoints"), num_train_epochs=a.epochs, learning_rate=a.lr,
            per_device_train_batch_size=1, per_device_eval_batch_size=1, prediction_loss_only=True,
            gradient_accumulation_steps=a.accum, bf16=True, optim="paged_adamw_8bit",
            lr_scheduler_type="cosine", warmup_steps=0.05, logging_steps=5,
            eval_strategy="epoch" if val_rows else "no", save_strategy="no", seed=a.seed,
            remove_unused_columns=False, report_to=[]))
    stats = trainer.train()
    report = {"train_loss": stats.training_loss}
    if val_rows:
        report["eval"] = trainer.evaluate()
    print(json.dumps(report, indent=2))
    adapter = out / "adapter"
    model.save_pretrained(str(adapter))
    tokenizer.save_pretrained(str(adapter))
    return adapter


def merge(base: str, adapter: Path) -> Path:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    merged = adapter.parent / "merged"
    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16, device_map={"": "cpu"})
    model = PeftModel.from_pretrained(model, str(adapter)).merge_and_unload()
    model.save_pretrained(str(merged), safe_serialization=True)
    AutoTokenizer.from_pretrained(str(adapter)).save_pretrained(str(merged))
    print(f"Merged model at {merged}")
    return merged


def main():
    p = argparse.ArgumentParser(description="QLoRA fine-tune of the answering model on the verified SFT set")
    p.add_argument("--base", default="Qwen/Qwen3-4B-Instruct-2507")
    p.add_argument("--name", default="pleiades-chat-4b")
    p.add_argument("--epochs", type=float, default=2)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--max-len", type=int, default=3072)
    p.add_argument("--accum", type=int, default=16)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-merge", action="store_true")
    a = p.parse_args()

    adapter = train(a)
    if not a.no_merge:
        merge(a.base, adapter)


if __name__ == "__main__":
    main()
