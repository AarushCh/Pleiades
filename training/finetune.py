import argparse
import json


def main():
    p = argparse.ArgumentParser(description="QLoRA fine-tune of Llama 3.1 8B Instruct on the Pleiades SFT set")
    p.add_argument("--train", default="sft_train.jsonl")
    p.add_argument("--val", default="sft_val.jsonl")
    p.add_argument("--base", default="unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit")
    p.add_argument("--out", default="pleiades-llama3.1-8b")
    p.add_argument("--epochs", type=float, default=2)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--max-len", type=int, default=4096)
    p.add_argument("--batch", type=int, default=2)
    p.add_argument("--accum", type=int, default=4)
    p.add_argument("--gguf", default="q4_k_m", help="empty to skip GGUF export")
    a = p.parse_args()

    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import get_chat_template, train_on_responses_only

    model, tokenizer = FastLanguageModel.from_pretrained(a.base, max_seq_length=a.max_len, load_in_4bit=True)
    tokenizer = get_chat_template(tokenizer, chat_template="llama-3.1")
    model = FastLanguageModel.get_peft_model(
        model, r=a.rank, lora_alpha=a.rank, lora_dropout=0, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=42)

    data = load_dataset("json", data_files={"train": a.train, "validation": a.val})
    data = data.map(lambda b: {"text": [tokenizer.apply_chat_template(m, tokenize=False) for m in b["messages"]]},
                    batched=True, remove_columns=data["train"].column_names)

    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=data["train"], eval_dataset=data["validation"],
        args=SFTConfig(
            dataset_text_field="text", max_seq_length=a.max_len, per_device_train_batch_size=a.batch,
            gradient_accumulation_steps=a.accum, num_train_epochs=a.epochs, learning_rate=a.lr,
            lr_scheduler_type="cosine", warmup_ratio=0.03, weight_decay=0.01, optim="adamw_8bit",
            logging_steps=10, eval_strategy="steps", eval_steps=50, save_strategy="steps", save_steps=50,
            save_total_limit=2, load_best_model_at_end=True, metric_for_best_model="eval_loss",
            seed=42, output_dir="checkpoints", report_to="none"))
    trainer = train_on_responses_only(trainer,
                                      instruction_part="<|start_header_id|>user<|end_header_id|>\n\n",
                                      response_part="<|start_header_id|>assistant<|end_header_id|>\n\n")
    stats = trainer.train()
    print(json.dumps({"train_loss": stats.training_loss, "eval": trainer.evaluate()}, indent=2))

    model.save_pretrained(a.out)
    tokenizer.save_pretrained(a.out)
    if a.gguf:
        model.save_pretrained_gguf(f"{a.out}-gguf", tokenizer, quantization_method=a.gguf)


if __name__ == "__main__":
    main()
