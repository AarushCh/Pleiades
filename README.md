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
| `.\run.ps1 test` | pytest suite (61 tests) |
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
                                                    grounded prompt ─► Llama 3 ─► draft
                                                                                       │
                       answer ◄── every figure found in the sources? ── no ─► redraft once, then hand over
```

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangChain (LCEL) and LangGraph | Chains for each model call; a graph for retrieve, draft, verify and hand over |
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

On Postgres the database enforces the same boundary with row-level security (`DB_RLS=1`). The
tenant is applied at the start of every transaction, so it survives commits and works behind a
transaction-mode pooler, and the app refuses to start if its database role could bypass the
policies. `tests/test_isolation.py` covers the boundary in the app; two more tests run only on
Postgres and check that the database itself hides and refuses other tenants' rows. Tests never
touch `DATABASE_URL`: point `TEST_DATABASE_URL` at a scratch database, such as a Neon branch, to
run them against Postgres.

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

| Configuration | Recall@6 |
|---|---|
| Vector only | 80.0% |
| With expansion and fusion, qwen3.8-27b expanding | **100.0%** |
| With expansion and fusion, gpt-oss-120b or gpt-oss-20b expanding | 86.7% |

Expansion is only as good as the model behind it, and with no working model it returns nothing
and recall drops to the vector-only 80.0%.

Fusion keeps the original question's top 2 hits. It used to keep 4, which cost a question: for
*"my card was declined, how long before you cut me off?"* the expander wrote the exact heading
of the right section, but four weak anchors filled four of the six places and pushed it to
seventh, and the model then correctly said the context didn't cover it. Replaying the same
expansions with 0 to 4 anchors gave 93.3%, 100%, 100%, 100% and 93.3%, so 2 sits in the middle
of the range that works.

The four cases expansion fixes are exactly the ones plain search gets wrong: the DOA clause,
the SLA credit table, the payment-failure timeline, and the RMA escalation remedy.

## Checking the answer before anyone sees it

A model that has the right passage can still write the wrong number. A refund window of 14 days
where the policy says 7 reads perfectly well, and it's the kind of mistake that costs money.

So the answer isn't streamed as it's written. `src/graph.py` runs each turn as a LangGraph:

1. **Retrieve.** The sources go to the client straight away, so the UI can show them.
2. **Draft.** The model writes a complete answer from the retrieved passages.
3. **Verify.** `src/grounding.py` pulls every figure out of the draft (prices, percentages,
   durations, model and ticket numbers) and checks each one against the passages, the
   customer's own question and the earlier turns. List numbering and "Step 3" don't count.
   There's no model call in this step, so it can't hallucinate an approval.
4. **Redraft or hand over.** If a figure isn't in the sources, the model gets one more try, told
   which figures it couldn't back up. If the second draft still has one, or the model returned
   nothing, the customer gets a short note that a person will pick it up instead of a guess.

The `done` event carries the outcome, the figures that failed and how many drafts it took.

What it doesn't catch yet: figures written as words ("seven days"), and arithmetic. A
correctly derived 90.4% uptime gets flagged because 90.4 doesn't appear in any source.
That's deliberate for now. The fix is to do the calculation in code and let the model explain
the result.

## Our own models

Pleiades trains its own models on the tenant's documents, on one RTX 4070 SUPER, at no cost.

### Training data

`training/product_data.py` has qwen3.8-27b, the best model in the answer benchmark, write six
questions per passage the way customers actually talk: symptoms instead of policy names, their
own words instead of the document's. A question is kept only if every figure in its answer
appears in the passage. Anything that copies or nearly copies a held-out eval question is
dropped, and train and validation are split by section, so validation only asks about passages
the model never trained on. The 41 Nimbus passages give 198 verified pairs.

The same run builds the answering model's set: the right passage hidden among the passages
retrieval really returns, off-topic questions that must be refused, and questions whose passage
has been removed, kept only when the figure check proves the remaining passages can't support
the answer, so the model isn't taught to refuse a question it could have answered.

### Pleiades-Embed, the retrieval encoder

`training/embed.py` fine-tunes a sentence encoder with in-batch negatives (no two questions
about the same passage in one batch), with the mean pooling and 256-token limit Chroma uses at
inference, and exports straight to ONNX in the layout Chroma loads. The export was checked
against the trained model (cosine 1.000000), and an export missing any file Chroma expects is
refused, because Chroma would quietly replace it with the stock model.

The model was chosen on the validation split; the human-written eval questions were only read
once, after choosing.

| Encoder | Recall@6, unseen sections | MRR | Recall@6, held-out questions |
|---|---|---|---|
| all-MiniLM-L6-v2, stock (the previous default) | 79.3% | 0.675 | 80.0% |
| bge-small-en-v1.5, stock | 82.8% | 0.684 | 80.0% |
| **bge-small-en-v1.5, fine-tuned 8 epochs** | **93.1%** | **0.740** | **86.7%** |

Most of the gain is the training rather than the base model. With query expansion on top, the
full pipeline still finds the right passage for every held-out question. The int8 export is
34 MB instead of 133 MB and embeds a query in 30 ms on a CPU with the same recall, so it fits a
512 MB free instance. Point `EMBED_MODEL_DIR` at the exported folder to use it; nothing else
changes, and it gets its own collection.

### Pleiades-Chat, the answering model (in progress)

`training/finetune.py` fine-tunes Qwen3-4B-Instruct-2507 (Apache-2.0) with QLoRA: 4-bit NF4
weights, LoRA rank 16 on every linear layer, and a loss computed only over the answer tokens,
with logits only produced for those tokens, which is what lets it train in 10 minutes inside
12 GB. The result is converted to a q8_0 GGUF with llama.cpp's converter and served by Ollama
(`training/Modelfile`).

To judge the answering model alone, every model below got the same retrieved passages, built
from the same query expansions, so the answer is the only thing that changes:

| Answering model | Correct (17) | p50 |
|---|---|---|
| qwen/qwen3.8-27b on Groq | 94.1% | 0.56 s |
| Qwen3-4B-Instruct, untrained, local | 94.1% | 1.79 s |
| Pleiades-Chat-4B, first fine-tune, local | 70.6% | 1.01 s |

The first fine-tune made the model worse. Its training answers were the short answers written
while the questions were being generated, each from a single passage and in a different style
from the production prompt, so it learned to be brief rather than complete. The replacement
(`product_data.py --distill`) runs the teacher through the production pipeline itself, with the
same prompts and the same retrieved passages, keeps only answers that pass the figure check on
the first draft, and adds the teacher's query expansions, which is where a 4B model falls short:
left to write its own expansions, untrained Qwen3-4B scores 76.5% end to end.

Running entirely offline, with Pleiades-Embed and untrained Qwen3-4B on one GPU, Pleiades
answers 82.4% of the benchmark correctly at a 2.3 s median.

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

### Answers, end to end

`python eval/run_answers.py` puts each question through the whole pipeline (retrieval, draft,
figure check) and scores the answer against facts taken from the documents, with paraphrase
allowed, plus two off-topic questions that must be refused. Each model was run on its own with
no fallbacks, paced under the free tier's rate limits so latency means model time.

| Model on Groq | Correct (17) | p50 | p95 |
|---|---|---|---|
| **qwen/qwen3.8-27b** | **94.1%** | **0.56 s** | 1.36 s |
| openai/gpt-oss-120b | 82.4% | 1.19 s | 2.34 s |
| openai/gpt-oss-20b | 82.4% | 1.07 s | 2.29 s |

Every failure was read before it counted, and two early "failures" turned out to be the eval
being stricter than the documents, so the eval was fixed. The one question qwen gets wrong is
the SLA credit: three days down is exactly 90.0% uptime, which earns 50%, and it chose the
"below 90%" row. Both figures are in the source, so the figure check can't catch it; the fix is
to do that lookup in code.

## Backends and failover

Auto-detected in order: Llama API → Groq → OpenRouter → Ollama → extractive stub. Hosted models
come first, so a local Ollama no longer quietly replaces a 27B model with an 8B one. Override
with `LLM_BACKEND` in `.env`.

| Backend | Setup | Notes |
|---|---|---|
| `llama-api` | `LLAMA_API_BASE`, `LLAMA_API_KEY`, `LLAMA_API_MODEL` | Any OpenAI-compatible host serving Llama 3 (Cerebras, SambaNova, NVIDIA, Together, a self-hosted vLLM). Recommended hosted default |
| `groq` | `GROQ_API_KEY=gsk_…` | Default. `GROQ_MODEL` (qwen/qwen3.8-27b) then each of `GROQ_FALLBACK_MODELS` (gpt-oss-120b, gpt-oss-20b). Every model has its own free quota |
| `ollama` | `.\setup.ps1 -WithOllama` | Fully offline, last in the automatic order |
| `openrouter` | `OPENROUTER_API_KEY=sk-or-v1-…` | Free Nemotron model by default; Llama 3.3 there needs credit on the key |
| `stub` | nothing | Extractive fallback so retrieval still demos with no model at all |

Every configured model that is not the primary becomes a LangChain fallback, including each
extra Groq model, so one retired or rate-limited model doesn't stop answers. That happened:
Groq retired every Llama model this project used to run on. All three current Groq models
reason before answering, so reasoning is set to low for gpt-oss and off for qwen; otherwise the
thinking can use up the answer's token budget.

At startup the chain is probed in order, and `/api/health` reports the model that actually
answered, plus any that failed, not the one that was configured. The UI shows a warning when
nothing is answering.

Groq's free tier is per organisation and per model: 1,000 requests and, for qwen3.8-27b,
200,000 tokens a day, refilled continuously. A turn costs 2,000 to 3,000 tokens, so qwen covers
about 80 turns a day before the chain moves on to the gpt-oss models, which have their own
allowance.

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
src/graph.py       LangGraph turn: retrieve, draft, verify, redraft or hand over
src/grounding.py   checks every figure in an answer against its sources
src/cli.py         terminal client
src/app.py         Streamlit UI (alternative to the Next.js one)
api/               FastAPI service, SSE streaming, session store
frontend/          Next.js app router, glass design system
tests/             61 tests, LLM-dependent ones skip unless a backend answers
training/          training data, the embedder and answering-model fine-tunes, the project assistant
eval/              retrieval benchmark (dataset.json) and answer benchmark (answers.json)
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
4. **Multi-document arithmetic.** "Down 3 days last month" needs the billing FAQ and the SLA
   table in the catalog together. Models like to work out an uptime figure such as 90.4%, which
   no source contains, so the check sends that draft back and the redraft has to quote the
   credit band from the table, or the customer is handed to a person.
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

`training/finetune.py` fine-tunes the answering model; see Our own models.
