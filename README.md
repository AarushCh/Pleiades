# Pleiades

Generative AI-based intelligent customer support over enterprise knowledge bases.

Retrieval-Augmented Generation over enterprise knowledge bases. A customer question is matched
against a ChromaDB index built from FAQs, product manuals, policy documents, a product catalog
and resolved support tickets, and the retrieved passages are handed to Llama 3 as grounding
context. Every answer cites the document and section it came from.

The demo tenant is **Nimbus Networks**, a fictional ISP.

## Quick start

```powershell
.\setup.ps1                  # venv, dependencies, .env, vector index
.\run.ps1                    # build the UI and serve everything on :8000
```

```bash
./setup.sh                   # macOS / Linux
```

| Command | What it does |
|---|---|
| `.\run.ps1` | Builds the Next.js UI and serves API + UI on `:8000` |
| `.\run.ps1 dev` | API with reload on `:8000`, Next dev server on `:5173` |
| `.\run.ps1 demo` | Scripted five-question walkthrough in the terminal |
| `.\run.ps1 cli` | Interactive terminal client |
| `.\run.ps1 test` | pytest suite (24 tests) |
| `.\run.ps1 eval` | Retrieval recall benchmark |
| `.\run.ps1 backend` | Reports which model is live and makes a test call |

Interactive API docs are at `/docs`. Docker: `docker build -t nimbus . && docker run -p 8000:8000 --env-file .env nimbus`.

## Architecture

```
                     ┌────────── Next.js app (static export) ─────────┐
                     │  streaming chat · source cards · pipeline trace │
                     └────────────────────┬───────────────────────────┘
                                          │  SSE
                     ┌────────────────────▼───────────────────────────┐
                     │  FastAPI  /api/chat · /api/search · /api/health │
                     └────────────────────┬───────────────────────────┘
                                          │
data/*.md ─► heading split ─► size split ─► MiniLM-L6-v2 (ONNX) ─► ChromaDB (cosine)
                                          │
question ─► condense (if follow-up) ─► expand ─► vector × N + BM25 ─► anchored fusion ─┐
                                                                                       ▼
                                                    grounded prompt ─► Llama 3 ─► answer
```

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangChain (LCEL) | Composable chains, swappable model backends |
| Vector store | ChromaDB, cosine, persisted | Zero-config, embedded, no server |
| Embeddings | all-MiniLM-L6-v2 via Chroma's ONNX runtime | ~80 MB instead of a multi-GB torch install |
| Generation | Llama 3 (Groq hosted, Ollama local) | Open weights, self-hostable for enterprise data |
| API | FastAPI + SSE | Token streaming, per-session history, OpenAPI docs |
| UI | Next.js (App Router, static export) | Glass design system, streaming answers, pipeline trace |

The frontend is a static export, so one FastAPI process serves both the API and the UI on a
single port. `npm run dev` instead runs Next on `:5173` and proxies `/api` to `:8000`.

## Deploying

Two services. Both have usable free tiers.

**1. Database — Supabase** (Neon works unchanged; the schema is plain Postgres)
Create a project, copy the connection string from Settings → Database, and set it as
`DATABASE_URL`. Run `python -m src.db` once to create the schema and seed the documents table.
Without `DATABASE_URL` the app falls back to a local SQLite file, so development needs no setup.

**2. App — Render** (`render.yaml` is committed; Railway and Fly.io work the same way)
Point Render at the repo and set four secrets:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase connection string |
| `DB_SCHEMA` | Postgres schema, defaults to `pleiades` |
| `GROQ_API_KEY` | from console.groq.com/keys |
| `JWT_SECRET` | generated automatically by `render.yaml` |
| `CORS_ORIGINS` | your deployed origin, only if the UI is hosted separately |

The Dockerfile builds the Next.js UI, installs the API, bakes the vector index into the image,
and honours the platform's `$PORT`. One container serves the API and the UI, so no CORS setup is
needed in the default single-origin deployment.

### Why Chroma still works in production

The index is built at image build time and read-only at runtime, so an ephemeral container
filesystem is not a problem. Rebuild the image when `data/` changes. Postgres holds the mutable
state: users, conversations, messages, and the document bodies the index is derived from.

### Ollama does not move to a server unchanged

Locally it is free because your machine provides the RAM. On a host you rent that RAM, and free
tiers cap memory below the ~5 GB Llama 3 8B needs.

| Option | Cost | When |
|---|---|---|
| Hosted Llama 3 API (Groq, Together, Fireworks) | Free tier or per-token | Default. No GPU, no cold start |
| Ollama on a CPU VM | ~8 GB instance, a few dollars a month | 10-30 s answers. Private demo only |
| Ollama on a GPU VM | Substantially more | Only when data cannot leave your infrastructure |
| Ollama on a free tier | Not possible | Memory caps sit below the model size |

Deploy with `LLM_BACKEND=groq` and the container needs no GPU and about 512 MB of RAM. If
on-premise inference is later required, point `OLLAMA_BASE_URL` at an Ollama box; nothing else
changes.

## Accounts and data

Signup and login are email plus a bcrypt-hashed password, with a signed JWT held in the browser
and verified on every request. Conversations and messages are written to Postgres and scoped to
their owner: requesting another user's conversation returns 404, not their data. Tests cover
that boundary.

The `documents` table is the source of truth for the knowledge base. `python -m src.ingest`
reads from it and falls back to `data/*.md` when the table is empty, so the corpus can be
edited in the database without touching the repository.

## Retrieval

Plain vector search fails on this corpus in ways worth showing, and the failures are not
subtle — they produce confidently wrong answers.

**Vocabulary mismatch.** Ask *"I was down for 3 days, do I get anything back?"* and the SLA
credit table does not appear in the top 12 results. The customer says *down* and *get anything
back*; the policy says *uptime achieved* and *service credit*. BM25 does not rescue it either,
because the vocabularies genuinely do not overlap.

**Clause selection.** Ask *"my router died 4 days after it arrived, do I need triage?"* and
vector search returns the RMA process section, which says triage is mandatory. The correct
answer is the DOA clause, which waives triage inside 7 days. Retrieval ranked it 7th.

So retrieval runs several ways and fuses them:

1. **Vector search** on the question exactly as asked.
2. **Query expansion** — the LLM rewrites the question into up to 3 queries in the knowledge
   base's own vocabulary. It is given the list of section headings that actually exist, which
   matters: blind expansion invented plausible-sounding clause names and retrieved nothing.
   Grounding the expander in real headings took DOA retrieval from 0/4 to 12/12.
3. **BM25 keyword search**, which catches exact tokens vector search dilutes: `RX-900`,
   `TKT-10231`, `POL-RW-004`.
4. **Anchored fusion** — results rank by maximum cosine similarity across every query, plus a
   bonus for keyword hits, but the original question's top hits are always kept. Without
   anchoring, a strong expansion match displaced correct chunks and expansion made three
   benchmark cases worse.

Reciprocal Rank Fusion was tried first and performed worse here: with four candidate lists it
spread rank mass across near-duplicates and pushed decisive chunks out of the top 5.

Follow-ups are condensed against chat history, but the **original** question is always
retrieved alongside the condensed one. Condensing alone silently dropped "4 days" from *"my
router died 4 days after it arrived"*, which flipped the DOA answer from correct to wrong.

### Measured

`.\run.ps1 eval` scores retrieval against 15 labelled questions in `eval/dataset.json`,
three runs each because expansion is non-deterministic.

| Configuration | Recall | p50 latency |
|---|---|---|
| Vector only | 80.0% | 12 ms |
| With expansion and fusion | **93.3%** | ~1.0 s |

The four cases expansion fixes are exactly the ones plain search gets wrong: the DOA clause,
the SLA credit table, the payment-failure timeline, and the RMA escalation remedy.

## Token budget

| Measure | Effect |
|---|---|
| System prompt compressed | ~150 → ~90 tokens |
| History capped at 2 turns, replies truncated to 220 chars | bounded growth over a session |
| Condensing skipped unless the question is referential or very short | removes a call on most turns |
| Duplicate chunks dropped from context | avoids paying twice for overlapping text |
| `MAX_TOKENS=500` | caps the generation side |

A typical grounded turn is ~900–1100 prompt tokens; the UI reports the estimate per answer.
Query expansion adds one small call (~360 tokens of section headings in, ~40 out). Set
`EXPAND_THRESHOLD=0` to disable it and trade recall for latency.

## Backends and failover

Auto-detected in order: Ollama → Groq → OpenRouter → extractive stub. Override with
`LLM_BACKEND` in `.env`.

| Backend | Setup | Notes |
|---|---|---|
| `groq` | `GROQ_API_KEY=gsk_…` from [console.groq.com/keys](https://console.groq.com/keys) | Llama 3.3 70B, ~0.7 s per answer. Current default. Free tier is capped at 100k tokens/day |
| `ollama` | `.\setup.ps1 -WithOllama` | Local Llama 3 8B, fully offline. ~7 s per answer and visibly weaker than 70B |
| `openrouter` | `OPENROUTER_API_KEY=sk-or-v1-…` | Free Nemotron model by default; Llama 3.3 there needs credit on the key |
| `stub` | nothing | Extractive fallback so retrieval still demos with no model at all |

Every configured backend that is not the primary becomes a LangChain fallback. If Groq returns
a rate-limit error mid-demo, the chain retries on Ollama and then OpenRouter rather than
failing. This is not theoretical — the daily token cap was hit while benchmarking, and the
failover is what kept the pipeline answering.

`python -m src.llm` reports the live backend, makes a test call, and on an unknown-model error
lists every model your key can actually reach.

## Layout

```
data/              enterprise knowledge base (5 markdown documents)
src/config.py      all tunables, .env driven
src/embeddings.py  LangChain Embeddings over Chroma's ONNX MiniLM
src/ingest.py      load → chunk → embed → persist (idempotent, --rebuild to wipe)
src/llm.py         backend selection, fallbacks, health check
src/rag.py         hybrid retrieval and grounded generation
src/cli.py         terminal client
src/app.py         Streamlit UI (alternative to the Next.js one)
api/               FastAPI service, SSE streaming, session store
frontend/          Next.js app router, glass design system
tests/             24 tests, LLM-dependent ones skip without a backend
eval/              labelled retrieval benchmark
```

## Adding your own knowledge base

Drop `.md` files into `data/`, add a display name to `SOURCE_LABELS` in `src/config.py`, and
re-run `python -m src.ingest`. Only new chunks are embedded.

## Demo script

`.\run.ps1 demo` covers the five behaviours worth showing:

1. **Cross-document synthesis** — the amber-LED question pulls the manual's LED table and the
   matching resolved ticket TKT-10231.
2. **Policy override** — "router died 4 days after delivery" must hit the DOA clause. Answering
   from the RMA section alone tells the customer to run triage, which is wrong.
3. **Structured lookup** — plan comparison retrieves the catalog table.
4. **Multi-document arithmetic** — "down 3 days last month" resolves to ~90.4% uptime and a 50%
   credit, combining the billing FAQ with the SLA table in the catalog.
5. **Refusal** — an out-of-scope question returns a one-line refusal and a human handoff
   instead of answering from the model's own knowledge.
