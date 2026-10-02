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
| `.\run.ps1 test` | pytest suite (48 tests) |
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
| Generation | Llama 3 (any OpenAI-compatible host, Ollama local) | Open weights, self-hostable for enterprise data |
| API | FastAPI + SSE | Token streaming, per-session history, OpenAPI docs |
| UI | Next.js (App Router, static export) | Glass design system, streaming answers, pipeline trace |

The frontend is a static export, so one FastAPI process serves both the API and the UI on a
single port. `npm run dev` instead runs Next on `:5173` and proxies `/api` to `:8000`.

## Deploying

Two services. Both have usable free tiers.

**1. Database: Supabase** (Neon works unchanged; the schema is plain Postgres)
Create a project, copy the connection string from Settings → Database, and set it as
`DATABASE_URL`. Run `python -m src.db` once to create the schema and seed the documents table.
Without `DATABASE_URL` the app falls back to a local SQLite file, so development needs no setup.

**2. App: Render** (`render.yaml` is committed; Railway and Fly.io work the same way)
Point Render at the repo and set these:

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
their owner: requesting another user's conversation returns 404, not their data.

### Organisations

One deployment serves many organisations, and none of them can see another's data. Every row in
`users`, `conversations`, `messages` and `documents` carries a `tenant_id`. Sign-up and sign-in
pick the organisation from the `X-Tenant` header (Nimbus Networks when it's absent); after that
the organisation travels inside the signed token and is checked against the account on every
request, so a token can't be replayed against another one. An email address is unique within an
organisation, not across them.

Each organisation gets its own Chroma collection rather than a share of one collection behind a
filter. A bug in retrieval can't reach documents it was never indexed next to.

Postgres row-level security is written and ready behind `DB_RLS=1`. It stays off until it has
been run against a live database. `tests/test_isolation.py` covers the boundary either way.

The `documents` table is the source of truth for the knowledge base. `python -m src.ingest`
reads from it and falls back to `data/*.md` when the table is empty, so the corpus can be
edited in the database without touching the repository.

## Retrieval

Plain vector search fails on this corpus in ways worth showing. The failures aren't subtle.
They produce confidently wrong answers.

**Vocabulary mismatch.** Ask *"I was down for 3 days, do I get anything back?"* and the SLA
credit table does not appear in the top 12 results. The customer says *down* and *get anything
back*; the policy says *uptime achieved* and *service credit*. BM25 does not rescue it either,
because the vocabularies genuinely do not overlap.

**Clause selection.** Ask *"my router died 4 days after it arrived, do I need triage?"* and
vector search returns the RMA process section, which says triage is mandatory. The correct
answer is the DOA clause, which waives triage inside 7 days. Retrieval ranked it 7th.

So retrieval runs several ways and fuses them:

1. **Vector search** on the question exactly as asked.
2. **Query expansion.** The LLM rewrites the question into up to 3 queries in the knowledge
   base's own vocabulary. It is given the list of section headings that actually exist, which
   matters: blind expansion invented plausible-sounding clause names and retrieved nothing.
   Grounding the expander in real headings took DOA retrieval from 0/4 to 12/12.
3. **BM25 keyword search**, which catches exact tokens vector search dilutes: `RX-900`,
   `TKT-10231`, `POL-RW-004`.
4. **Anchored fusion.** Results rank by maximum cosine similarity across every query, plus a
   bonus for keyword hits, but the original question's top hits are always kept. Without
   anchoring, a strong expansion match displaced correct chunks and expansion made three
   benchmark cases worse.

Reciprocal Rank Fusion (Cormack et al., k=60) is implemented and can be switched on with
`FUSION=rrf`. On vector plus BM25 it scores 73.3% against anchored fusion's 80.0%. It gives the
keyword list an equal vote, and for *"my RMA has been stuck"* that vote goes to every chunk that
mentions an RMA, which pushes the escalation section out of the top 6. Keeping the original
question's top hits fixes that, so anchored fusion stays the default. Fifteen questions is a
small set, one question moves recall by 6.7 points, and the comparison will be rerun on the
larger eval set.

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

The 93.3% was measured with Llama 3.3 70B on Groq. Expansion needs a model that answers: with
no working model it returns nothing and recall falls back to the vector-only 80.0%. A local
Llama 3 8B reaches 86.7%, because it tends to name one section instead of writing three queries.

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

Auto-detected in order: Ollama → Llama API → Groq → OpenRouter → extractive stub. Override with
`LLM_BACKEND` in `.env`.

| Backend | Setup | Notes |
|---|---|---|
| `llama-api` | `LLAMA_API_BASE`, `LLAMA_API_KEY`, `LLAMA_API_MODEL` | Any OpenAI-compatible host serving Llama 3 (Cerebras, SambaNova, NVIDIA, Together, a self-hosted vLLM). Recommended hosted default |
| `groq` | `GROQ_API_KEY=gsk_…` | Groq has retired its Llama 3 chat models; set `GROQ_MODEL` to a model your key lists, or leave Groq as a fallback only |
| `ollama` | `.\setup.ps1 -WithOllama` | Local Llama 3 8B, fully offline. ~7 s per answer and visibly weaker than 70B |
| `openrouter` | `OPENROUTER_API_KEY=sk-or-v1-…` | Free Nemotron model by default; Llama 3.3 there needs credit on the key |
| `stub` | nothing | Extractive fallback so retrieval still demos with no model at all |

Every configured backend that is not the primary becomes a LangChain fallback. If Groq returns
a rate-limit error mid-demo, the chain retries on Ollama and then OpenRouter rather than
failing. We hit Groq's daily token cap while benchmarking, and the failover is what kept the
pipeline answering.

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
tests/             48 tests, LLM-dependent ones skip unless a backend answers
training/          project assistant: corpus, dataset, QLoRA fine-tune, evaluation
eval/              labelled retrieval benchmark
```

## Adding your own knowledge base

Drop `.md` files into `data/`, add a display name to `SOURCE_LABELS` in `src/config.py`, and
re-run `python -m src.ingest`. Only new chunks are embedded.

## Demo script

`.\run.ps1 demo` covers the five behaviours worth showing:

1. **Cross-document synthesis.** The amber-LED question pulls the manual's LED table and the
   matching resolved ticket TKT-10231.
2. **Policy override.** "Router died 4 days after delivery" must hit the DOA clause. Answering
   from the RMA section alone tells the customer to run triage, which is wrong.
3. **Structured lookup.** Plan comparison retrieves the catalog table.
4. **Multi-document arithmetic.** "Down 3 days last month" resolves to ~90.4% uptime and a 50%
   credit, combining the billing FAQ with the SLA table in the catalog.
5. **Refusal.** An out-of-scope question returns a one-line refusal and a human handoff
   instead of answering from the model's own knowledge.

## Project assistant

The same pipeline can answer questions about this repository itself: code, data, decisions,
deployment and roadmap.

| Command | What it does |
|---|---|
| `python training/pipeline.py build` | Collect the project corpus and index it |
| `python training/pipeline.py chat` | Ask in the terminal |
| `python training/pipeline.py serve` | Web UI on `:8100` |
| `python training/pipeline.py eval --answers` | Score on the golden set |
| `python training/pipeline.py dataset` | Generate verified fine-tuning data |

`training/finetune.py` runs QLoRA on Llama 3.1 8B on a GPU and exports a GGUF for Ollama.
