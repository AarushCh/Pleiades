FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin pleiades
ENV HOME=/home/pleiades

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

ARG EMBED_REPO=AUC6/pleiades-embed
ARG EMBED_REVISION=a2a24ce968be8f0fae861b25badf38d20198fa8c
ENV EMBED_MODEL_DIR=/app/models/pleiades-embed
RUN mkdir -p "$EMBED_MODEL_DIR/onnx" \
    && for f in config.json model.onnx special_tokens_map.json tokenizer_config.json tokenizer.json vocab.txt; do \
         curl -fsSL -o "$EMBED_MODEL_DIR/onnx/$f" "https://huggingface.co/$EMBED_REPO/resolve/$EMBED_REVISION/onnx/$f"; \
       done

COPY src/ ./src/
COPY api/ ./api/
COPY data/ ./data/
COPY eval/ ./eval/
COPY --from=ui /ui/out ./frontend/out

RUN python -m src.ingest && chown -R pleiades:pleiades /app /home/pleiades

USER pleiades

ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD curl -fsS http://localhost:${PORT:-8000}/api/health || exit 1

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
