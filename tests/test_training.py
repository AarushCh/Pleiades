from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "pipeline", Path(__file__).resolve().parent.parent / "training" / "pipeline.py"
)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def test_verified_pairs_drop_invented_numbers_and_names():
    passage = "Nimbus Plus costs ₹899 per month. Set `LLAMA_API_KEY` on Render."
    raw = (
        'Sure: [{"question": "What does Nimbus Plus cost per month?", "answer": "It costs ₹899 per month."},'
        ' {"question": "What does Nimbus Plus cost per year?", "answer": "It costs ₹10,788 per year."},'
        ' {"question": "Which variable holds the key?", "answer": "Set `LLAMA_API_TOKEN` on Render."},'
        ' {"question": "Which variable holds the Llama key?", "answer": "Set `LLAMA_API_KEY` on Render."}]'
    )
    kept = [p["answer"] for p in pipeline.verified_pairs(raw, passage)]
    assert kept == ["It costs ₹899 per month.", "Set `LLAMA_API_KEY` on Render."]


def test_verified_pairs_survive_malformed_output():
    assert pipeline.verified_pairs("no json here", "passage") == []
    assert pipeline.verified_pairs('[{"question": 1}]', "passage") == []


def test_secrets_are_redacted():
    text = "key gsk_" + "a" * 30 + " url postgresql+psycopg://user:pw@host/db"
    cleaned = pipeline.SECRET.sub("[REDACTED]", text)
    assert "gsk_" not in cleaned
    assert "pw@" not in cleaned
