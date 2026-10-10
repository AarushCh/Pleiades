import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish an exported embedder to the Hugging Face Hub")
    parser.add_argument("repo", help="for example your-name/pleiades-embed")
    parser.add_argument("--model-dir", type=Path, default=HERE / "build" / "models" / "pe-bge-e8-int8")
    parser.add_argument("--card", type=Path, default=HERE / "embed_card.md")
    args = parser.parse_args()

    from huggingface_hub import HfApi

    if not (args.model_dir / "onnx" / "model.onnx").exists():
        raise SystemExit(f"No exported model in {args.model_dir}")
    shutil.copy(args.card, args.model_dir / "README.md")
    api = HfApi()
    api.create_repo(args.repo, exist_ok=True)
    api.upload_folder(folder_path=str(args.model_dir), repo_id=args.repo, allow_patterns=["README.md", "onnx/*"],
                      commit_message="Publish the int8 ONNX export")
    print(f"https://huggingface.co/{args.repo}")


if __name__ == "__main__":
    main()
