#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

WITH_OLLAMA=0
[[ "${1:-}" == "--with-ollama" ]] && WITH_OLLAMA=1

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

step "Python environment"
PY=".venv/bin/python"
if [[ ! -x "$PY" ]]; then
    if command -v uv >/dev/null; then uv venv --python 3.13 .venv; else python3 -m venv .venv; fi
fi
if command -v uv >/dev/null; then
    uv pip install --python "$PY" -r requirements.txt
else
    "$PY" -m pip install --upgrade pip && "$PY" -m pip install -r requirements.txt
fi

step "Configuration"
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Created .env - add an API key, or use --with-ollama for a local model."
fi

step "Vector index"
"$PY" -m src.ingest

if [[ $WITH_OLLAMA -eq 1 ]]; then
    step "Ollama"
    command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh

    MODEL=$(grep -E '^OLLAMA_MODEL=' .env 2>/dev/null | cut -d= -f2- | tr -d ' ' || true)
    MODEL=${MODEL:-llama3}

    curl -sf http://localhost:11434/api/tags >/dev/null || { ollama serve >/dev/null 2>&1 & sleep 5; }

    echo "Pulling $MODEL (~4.7 GB, one time)..."
    ollama pull "$MODEL"
fi

step "Backend check"
"$PY" -m src.llm

printf '\n\033[32mReady.\033[0m\n'
echo "  .venv/bin/streamlit run src/app.py"
echo "  .venv/bin/python -m src.cli --demo"
