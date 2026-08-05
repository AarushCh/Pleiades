from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
CHROMA_DIR = ROOT / "chroma_db"
COLLECTION_NAME = "enterprise_kb"
DISTANCE_METRIC = "cosine"

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

TOP_K = int(os.getenv("TOP_K", "6"))
MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.12"))
EXPAND_THRESHOLD = float(os.getenv("EXPAND_THRESHOLD", "0.75"))
KEYWORD_BONUS = 0.06
ANCHORS = 4

LLM_BACKEND = os.getenv("LLM_BACKEND", "auto").lower()
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "500"))

HISTORY_TURNS = 2
HISTORY_REPLY_CHARS = 220

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

SOURCE_LABELS = {
    "faq_billing.md": "Billing FAQ",
    "manual_nimbus_router.md": "RX-500/RX-900 Router Manual",
    "policy_returns_warranty.md": "Returns & Warranty Policy (POL-RW-004)",
    "product_catalog.md": "Product & Plan Catalog 2026",
    "support_tickets_history.md": "Historical Support Tickets",
}
