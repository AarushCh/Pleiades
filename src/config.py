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

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
TOKEN_DAYS = int(os.getenv("TOKEN_DAYS", "7"))
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}
CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
TRUST_PROXY = os.getenv("TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}

LLM_BACKEND = os.getenv("LLM_BACKEND", "auto").lower()
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "500"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))

HISTORY_TURNS = 2
HISTORY_REPLY_CHARS = 220

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

LLAMA_API_BASE = os.getenv("LLAMA_API_BASE", "").strip().rstrip("/")
LLAMA_API_KEY = os.getenv("LLAMA_API_KEY", "").strip()
LLAMA_API_MODEL = os.getenv("LLAMA_API_MODEL", "llama-3.3-70b")

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
