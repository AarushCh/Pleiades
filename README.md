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
| `.\run.ps1` | Builds the Next.js UI and serves API + UI on `:8000`, reloading on backend edits |
| `.\run.ps1 dev` | API with reload on `:8000`, Next dev server on `:5173` |
| `.\run.ps1 demo` | Scripted five-question walkthrough in the terminal |
| `.\run.ps1 cli` | Interactive terminal client |
| `.\run.ps1 test` | pytest suite (111 tests) |
| `.\run.ps1 eval` | Retrieval recall benchmark |
| `.\run.ps1 backend` | Reports which model is live and makes a test call |

Interactive API docs are at `/docs`. Docker: `docker build -t nimbus . && docker run -p 8000:8000 --env-file .env nimbus`.

Every install (the setup scripts, CI and the Docker image) uses the exact versions pinned in
`requirements.lock`, so a new upstream release can't change a build that already passed. To
change a dependency, edit `requirements.txt` and recompile the lock:
`uv pip compile requirements.txt --universal --python-version 3.13 --no-header --no-annotate -o requirements.lock`.

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
| Embeddings | Pleiades-Embed (bge-small fine-tuned here, int8 ONNX) via Chroma's ONNX runtime | 34 MB, 30 ms a query on a CPU, trained on the tenant's documents |
| Generation | Llama 3 (any OpenAI-compatible host, Ollama local) | Open weights, self-hostable for enterprise data |
| API | FastAPI + SSE | Token streaming, per-session history, OpenAPI docs |
| UI | Next.js (App Router, static export) | Glass design system, streaming answers, pipeline trace |

The frontend is a static export, so one FastAPI process serves both the API and the UI on a
single port. `npm run dev` instead runs Next on `:5173` and proxies `/api` to `:8000`.

## Deploying

Two services. Both have usable free tiers.

**1. Database: Neon** (any Postgres works; Neon's free tier suspends when idle instead of pausing)
Put the owner's connection string in `.env` as `DATABASE_ADMIN_URL` and run
`python -m src.db setup` once. It creates the schema, applies the Alembic migrations in
`src/migrations`, turns on row-level security, creates a `pleiades_app` role that can read and
write rows but can't bypass the policies or change the schema, seeds the documents, and writes
that role's connection string into `.env` as `DATABASE_URL`, so it never has to be shown. The app
runs as that role, so it can't migrate anything itself: it checks the schema revision at startup
and refuses to run against an older one. Run setup again whenever a migration is added; it is
safe to repeat, and a database created before migrations existed is adopted at the baseline.
Without `DATABASE_URL` the app falls back to a local SQLite file and migrates it itself, so
development needs no setup.

**2. App: Render** (`render.yaml` is committed; Railway and Fly.io work the same way)
Point Render at the repo and set these:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the `pleiades_app` connection string that setup wrote to `.env` |
| `DB_RLS` | `1`, so the app checks that row-level security is enforced before it serves |
| `DB_SCHEMA` | Postgres schema, defaults to `pleiades` |
| `GROQ_API_KEY` | from console.groq.com/keys |
| `JWT_SECRET` | generated automatically by `render.yaml` |
| `CORS_ORIGINS` | your deployed origin, only if the UI is hosted separately |
| `CHAT_DAILY_LIMIT` | questions per account in any 24 hours, defaults to 30; admins are exempt |
| `TRUST_PROXY`, `PROXY_HOPS` | `1` and `2` on Render. Rate limits key on the client's address, and Render's proxy appends to `X-Forwarded-For` instead of replacing it, so the first entry is whatever the client wrote; the real one is `PROXY_HOPS` from the right |

The Dockerfile builds the Next.js UI, installs the API, bakes the vector index into the image,
and honours the platform's `$PORT`. One container serves the API and the UI, so no CORS setup is
needed in the default single-origin deployment.

After a deploy, `/api/health` says which database it reached (`primary` or the SQLite
`fallback`), the schema revision the code runs against, and `rls`. `rls: true` means the app is
connected as a role the policies bind and every tenant table is enforcing them.

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

Signup and login are email plus a bcrypt-hashed password. The signed token lives in an
HttpOnly, SameSite=Strict cookie scoped to `/api` (Secure behind HTTPS), so scripts on the page
never see it and other sites can't make the browser send it; API clients can send the same token
as a Bearer header. Every token carries the account's session version, and signing out bumps it,
which revokes every token issued before, on every device. Conversations and messages are written
to Postgres and scoped to their owner: requesting another user's conversation returns 404, not
their data.

Each account gets `CHAT_DAILY_LIMIT` questions (30) in any rolling 24 hours, and six a minute.
The models run on free tiers whose daily allowance everyone shares, so one visitor can't use it
up for the rest.

Every answer has Helpful and Not helpful under it, with an optional reason for the second, and
only the person who asked can rate it. Admins get the latest complaints in their organisation,
with the question, the answer, the reason and the sources, at `GET /api/admin/feedback`. That
queue is where new benchmark cases come from.

Admin is a flag on the account, never a property of the email address, because anyone can sign up
with any address. Sign up first, then grant it from a machine holding the database credentials:
`python -m src.db admin you@example.com` (add an organisation slug for another organisation, and
`off` to take it away).

Admins get an **Admin console** in the sidebar: the last 7 days at a glance (questions, how many
were answered without a person, how many were handed over, helpful and not helpful, how many
people asked), the handover queue (every question the figure check passed to a person, with who
asked it, at `GET /api/admin/handovers`), the complaints, sign-up access, and an index rebuild.
Each answer's outcome is stored with it, and a handed-over answer tells the customer it went to
the support team. Customers can also hand any answer over themselves with Talk to a person
(`POST /api/messages/{id}/handover`, owner only); those join the same queue, marked as asked for.

### Organisations

One deployment serves many organisations, and none of them can see another's data. Every row in
`users`, `conversations`, `messages` and `documents` carries a `tenant_id`. Sign-up and sign-in
pick the organisation from the `X-Tenant` header (Nimbus Networks when it's absent); after that
the organisation travels inside the signed token and is checked against the account on every
request, so a token can't be replayed against another one. An email address is unique within an
organisation, not across them. An organisation is open to sign-up by default; its admin can make
it invite-only with `POST /api/admin/join-code`, which returns a code new accounts must send as
`join_code` (a fresh call replaces it, and `DELETE` opens sign-up again).

Each organisation gets its own Chroma collection rather than a share of one collection behind a
filter. A bug in retrieval can't reach documents it was never indexed next to. The answer prompt
names the organisation the assistant is serving, taken from its row in `tenants`; it used to say
Nimbus Networks to everyone, which nudged the model into refusing questions about any other
company's documents. Indexing writes in batches of 5,000 chunks, below Chroma's limit, so a
knowledge base the size of TechQA's (36,670 chunks) indexes instead of failing.

On Postgres the database enforces the same boundary with row-level security (`DB_RLS=1`). The
tenant is applied at the start of every transaction, so it survives commits and works behind a
transaction-mode pooler. The role a hosted database gives you often can't be held to the
policies: Neon's `neondb_owner` has `BYPASSRLS`, so policies would simply not apply to it. That is
why setup creates a separate runtime role, and why the app refuses to start when its role could
bypass the policies or any tenant table isn't enforcing them. `tests/test_isolation.py` covers the boundary in the app; two more tests run only on
Postgres and check that the database itself hides and refuses other tenants' rows. Tests never
touch `DATABASE_URL`. To run them against Postgres, give them a schema of their own with
`DB_SCHEMA=pleiades_test python -m src.db setup`, then run pytest with
`TEST_DATABASE_URL=<the app role's string> DB_SCHEMA=pleiades_test DB_RLS=1`. On Neon, all of
the isolation and API tests pass that way, and removing the policy from a single table stops the
app from starting.

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

Short or referential follow-ups are condensed against chat history by the model, but the
**original** question is always retrieved alongside the condensed one. Condensing alone silently
dropped "4 days" from *"my router died 4 days after it arrived"*, which flipped the DOA answer
from correct to wrong. Other follow-ups, and all of them without a model, are searched with the
last exchange as well (see [Follow-up questions](#follow-up-questions)).

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

### Measured on someone else's documents

The labelled set above was written for these documents, so it can't show whether the design holds
up anywhere else. `python eval/doc2dial.py` downloads doc2dial (IBM, CC BY 3.0): 488 support
documents from four US government services (Social Security, Veterans Affairs, Federal Student Aid
and a DMV) and conversations whose first question a person wrote while reading the document, with
the exact span that answers it. All 488 documents become one organisation (3,997 chunks) under the
production chunker and retrieval, with no model involved, and a question counts as found when a
retrieved chunk holds its annotated span. Validation split, 661 questions, top 6 (what the model
reads):

| Encoder | Vector | Keyword | **Hybrid** | Hybrid, right document |
|---|---|---|---|---|
| all-MiniLM-L6-v2, stock | 64.1% | 64.0% | 68.7% | 79.7% |
| bge-small-en-v1.5, stock | 68.5% | 64.0% | 72.3% | 82.3% |
| Pleiades-Embed, full precision | 71.3% | 64.0% | **74.6%** | 84.7% |
| Pleiades-Embed, int8 (deployed) | 70.0% | 64.0% | 72.8% | 81.7% |

Fusion beats either retriever alone with every encoder, so hybrid retrieval isn't an artefact of
the home corpus. Pleiades-Embed saw only Nimbus questions in training and still gains 2.3 points
over its base on documents it never saw, so one encoder can serve other organisations; on Nimbus
the training was most of the gain, here the base model is. The int8 export, which matched full
precision on Nimbus, gives back 1.8 of those points on unfamiliar text; that is the price of
fitting a 512 MB free instance. First place is the encoder's call, because fusion keeps its top
two: with MiniLM that put the right passage first 27.2% of the time against keyword search's
38.4%, and with Pleiades-Embed the two are level (39.0%).

Tuning fusion on this set (validation to choose, the 661-question test split to confirm, the
Nimbus set to guard): raising the keyword bonus from 0.06 to 0.3 never helped. Dropping the two
anchors put the right passage first on 41.1% of test questions instead of 36.6% at the same
recall@6, but on Nimbus with query expansion zero anchors loses a question (see above). Keeping the
anchors in the six but ordering the six by fused score splits the difference the wrong way: first
place rises to 39.9% on doc2dial's test split and falls from 9 to 7 of 15 on Nimbus, where the
tuned encoder's own top hit is better. The six passages the model reads are the same either way, so
production keeps the anchors first.

### More organisations, written by other people

Each script below downloads a pinned copy, turns it into one organisation's knowledge base and
scores production retrieval (hybrid, no model) on questions the dataset's authors labelled.

| Benchmark | Knowledge base | Questions | Found @1 | @6 | @10 |
|---|---|---|---|---|---|
| `eval/repliqa.py`: RepLiQA, the right document | 300 made-up company policies, incident reports, small-business and security news (2,991 chunks) | 1,202 answerable | 79.6% | 96.3% | 97.2% |
| `eval/abcd.py`: ABCD, the agent guideline for the customer's request, from their first message | AcmeBrands' 55 agent procedures (118 chunks) | 1,004 test conversations | 39.7% | 73.3% | 79.3% |
| the same, from the first two messages | | | 46.4% | 81.5% | 86.4% |
| `eval/tau2.py`: τ²-bench telecom, the troubleshooting path for the complaint | Tech support manual, workflow, agent policy and plans (90 chunks) | 114 base tasks | 100% | 100% | 100% |
| the same, sections for every fix the task needs, from the customer's words | | | 0.0% | 19.4% | 36.0% |
| the same, from the agent's ticket | | | 3.4% | 50.0% | 62.0% |
| `eval/techqa.py`: TechQA, the technote that answers it | 6,974 IBM technotes, every question's candidates pooled (36,670 chunks) | 160 answerable dev questions | 41.2% | 70.6% | 74.4% |

RepLiQA's documents are invented, so no model has seen them; retrieval finds the right one 96% of
the time in the top six. ABCD measures routing: real customer openers like "I need to return an
item" to the right one of 55 procedures. A second message helps by eight points, which is why the
history matters (see follow-ups below). τ²-bench shows the limit of one-shot retrieval on
diagnosis: the right troubleshooting path is found every time, but the actual fixes (airplane
mode, APN reset, roaming) depend on the phone's hidden state, so they come up only when someone
describes the symptoms in detail, as the agent's ticket does. Walking a customer through those
checks is a multi-turn job, the agentic support item on the roadmap. TechQA is the hardest: real
IBM forum questions, often a pasted error log, against thousands of near-identical product
technotes; the answering one is in the top six seven times in ten.

### Follow-up questions

Customers ask "what about the other one?" and "do I need to bring anything?". `python
eval/doc2dial.py --follow-ups` takes MultiDoc2Dial (IBM, Apache-2.0), which reuses doc2dial's 488
documents, and asks every follow-up in a split with no model; the target is the passage the
agent's reply was written from. On the test split's 3,675 follow-ups:

| Searched with | Passage @1 | @3 | @6 | @10 | Document @1 | @3 | @6 | @10 |
|---|---|---|---|---|---|---|---|---|
| The follow-up alone | 15.6% | 29.5% | 38.2% | 42.2% | 24.0% | 38.2% | 46.0% | 50.3% |
| Plus the previous question | 20.4% | 38.9% | 51.5% | 57.6% | 37.3% | 58.4% | 68.0% | 72.8% |
| Plus the last exchange | 23.9% | 42.8% | 55.8% | 62.9% | 46.7% | 67.6% | 77.8% | 82.5% |
| **Pleiades: both searches** | **24.0%** | **47.1%** | **60.5%** | **68.6%** | **47.1%** | **69.1%** | **79.0%** | **84.1%** |

Searching with the follow-up alone, which is what Pleiades did without a model, misses most of
them. Adding the last question and the start of the last answer fixes much of that, and keeping
both searches beats either one, so retrieval runs the follow-up on its own and with the last
exchange, puts the second search's top hit first and the follow-up's own top hit second, and
fills the rest by score. The order was chosen on the validation split (3,767 follow-ups): with the
follow-up's own hit first, the right passage came first 15.5% of the time; with the exchange's hit
first, 20.8%, and nothing from @3 on changes. The test split above confirms it. It costs one more
vector search and no model call, and a conversation's first question is untouched. With a model
answering, short or referential follow-ups ("what about it?") are rewritten by the model instead.

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

Arithmetic is done in code, not by the model. When a customer gives an outage length and the
retrieved documents include an uptime-to-credit table, `src/sla.py` reads that table, works out
the month's uptime over 30 days and picks the row. The result goes into the context marked as
an exact calculation, so the model quotes it and the figure check accepts it. A number the
documents spell out supports the same number in digits ("seven days", "twenty-three", "third",
"1.5 million", "2 lakh"), and times are compared on the 24-hour clock, so "10 pm" matches "22:00".
Answers stay strict: a number the model spells out isn't checked, but it never fails a check either.

### Measured on RAGTruth

`python eval/ragtruth.py` scores the figure check on RAGTruth (Niu et al., ACL 2024, MIT): 2,700
test answers written by six models for question answering, summarisation and data-to-text, with
every hallucinated span marked by annotators. An answer counts as caught when a figure the check
rejects lies inside a span marked as hallucinated.

| Task | Answers | With a hallucinated figure | Caught | Clean answers wrongly flagged | Flags that were right |
|---|---|---|---|---|---|
| Question answering | 900 | 58 | 50.0% | 0.9% (was 1.2%) | 82.1% (was 78.0%) |
| Summaries | 900 | 47 | 53.2% | 11.9% (was 14.4%) | 35.2% (was 31.5%) |
| Data to text | 900 | 143 | 44.1% (was 48.3%) | 2.8% (was 19.0%) | 90.5% (was 67.7%) |
| All | 2,700 | 248 | 47.2% (was 49.6%) | 5.6% (was 9.7%) | 62.2% (was 54.8%) |

The "was" figures are the check before it read number words and both clocks. The wrongly flagged
data-to-text answers were nearly all opening hours ("2:00 pm" against "14:00"), which is exactly
what a support bot quoting a help centre's hours would have hit: Nimbus's own help centre says
"08:00 to 22:00 IST", and "8 am to 10 pm" used to fail. About half the hallucinated figures are
caught; the rest are numbers that do appear in the source but in the wrong place, which a string
check can't see. Summaries still trip it 11.9% of the time: models announcing their own word count
("in 84 words or less"), and figures added from outside the article, some plainly wrong but left
unmarked (one summary launches Hillary Clinton's 2020 campaign in a 2015 article).

### Why off-topic questions aren't refused earlier

Refusing before the draft would save the answer call on questions the documents can't answer.
Three ways of doing it were measured, and none was safe enough to ship.

- **A similarity floor.** With Pleiades-Embed, the closest passage for 231 in-domain questions
  (both benchmarks plus the teacher-written customer questions) scores as low as 0.368, and
  terse ones go lower: "fiber cut in my area" scores 0.315. Meanwhile 22 off-topic questions score
  as high as 0.562 ("How do I reset my Instagram password?" lands on the router's reset section).
  Any floor either turns customers away or catches almost nothing.
- **Letting the query expander answer NONE.** It already runs for nearly every question, so a
  relevance verdict would cost nothing extra. Both models caught all 22 off-topic questions, but
  qwen also declined 3 of the first 29 in-domain ones, including "no net since morning", and
  gpt-oss-120b, with a stricter instruction, still declined 2 of 48: "fiber cut in my area" and
  "can i get a refund if i change my mind?".
- **A classifier on the question's embedding.** `python eval/abstain.py` trains a logistic
  regression (numpy, no model call) on 9,360 support questions (Bitext Telco and customer
  service, ABCD openers) against 8,100 others (CLINC150's out-of-scope and non-banking intents,
  MASSIVE's assistant commands), sets the threshold to keep 99.8% of held-out support questions,
  and never refuses when a passage scores 0.5 or more. It keeps every Nimbus benchmark question,
  99.6 to 99.8% of held-out support questions and 98.8% of Banking77's banking ones, refuses
  both must-refuse questions, and catches 57% of CLINC150's out-of-scope questions and 79% of
  MASSIVE's. But it turns away 5 of 30 short and code-mixed support questions: "slow", "bill",
  "speed test", "plan kaise change karu" and "నా ఇంటర్నెట్ పని చేయడం లేదు" (Telugu for "my
  internet isn't working"). Its training data has no terse or code-mixed support questions, and
  the English encoder reads other scripts poorly, which is also why it refuses 97 to 99.8% of
  off-topic Telugu, Kannada and Malayalam but only 8% of Hindi. Set to keep 99.5% instead, it
  also refused "no net since morning".

Telling someone whose internet is down that support can't help costs far more than the 2,000 to
3,000 tokens an off-topic question uses, and one-word questions and Hinglish are how many
customers actually type. So the answer step stays the judge. It sees the retrieved passages
before deciding, and qwen refuses both must-refuse questions in the benchmark. The classifier is
worth revisiting with a multilingual encoder and real short, code-mixed support questions to
train on.

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
512 MB free instance. It is published at
[huggingface.co/AUC6/pleiades-embed](https://huggingface.co/AUC6/pleiades-embed), and the
Dockerfile downloads it at a pinned revision, so production serves exactly the model that was
measured. Locally, point `EMBED_MODEL_DIR` at the exported folder; nothing else changes, and it
gets its own collection. `/api/health` reports which encoder is running.

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
being stricter than the documents, so the eval was fixed. The one question qwen got wrong was
the SLA credit: three days down is exactly 90.0% uptime, which earns 50%, and it chose the
"below 90%" row. Both figures are in the source, so the figure check couldn't catch it. That
lookup now happens in code and the answer comes back right. No other question in the benchmark
triggers the calculation, so their prompts are unchanged.

## Security

Sessions live in an HttpOnly, SameSite=Strict cookie and sign-out revokes every earlier token;
each organisation's rows are fenced by Postgres row-level security under a role that can't bypass
it; admin is a flag on the account and an organisation can require a join code; sign-up, sign-in
and chat are rate-limited by an address the client can't forge behind Render's proxy; errors stay
in the server log; and every response carries a Content-Security-Policy that admits only this
origin's scripts and the build's own inline ones by hash, plus HSTS and nosniff. Each of these has
a test that fails when the protection is removed.

Scanner findings that don't apply, so nobody re-investigates them:

| Finding | Why it doesn't apply |
|---|---|
| pip-audit: chromadb advisories | They concern Chroma's HTTP server; Pleiades runs Chroma embedded, in-process, with no server |
| bandit B310: `urlopen` in `src/llm.py` | The URLs come from the operator's own environment (`OLLAMA_BASE_URL` and the like), never from a request |
| bandit B106: `token=""` in `/api/auth/me` | An empty field in a response, not a password |

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
data/              enterprise knowledge base (6 markdown documents)
src/config.py      all tunables, .env driven
src/embeddings.py  LangChain Embeddings over Chroma's ONNX MiniLM
src/ingest.py      load → chunk → embed → persist (idempotent, --rebuild to wipe)
src/llm.py         backend selection, fallbacks, health check
src/rag.py         hybrid retrieval and grounded generation
src/graph.py       LangGraph turn: retrieve, draft, verify, redraft or hand over
src/grounding.py   checks every figure in an answer against its sources
src/sla.py         works out SLA uptime and the credit row in code
src/db.py          models, row-level security, setup, migrations runner
src/migrations/    Alembic migrations
src/cli.py         terminal client
src/app.py         Streamlit UI (alternative to the Next.js one)
api/               FastAPI service, SSE streaming, session store
frontend/          Next.js app router, glass design system
tests/             111 tests, LLM-dependent ones skip unless a backend answers
training/          training data, the embedder and answering-model fine-tunes, the project assistant
eval/              retrieval and answer benchmarks, doc2dial recall, Bitext intent coverage
```

## Data and licences

| Source | Licence | Used for | In this repository |
|---|---|---|---|
| `data/*.md`, the Nimbus Networks documents | Written for this project; Nimbus is fictional | The demo organisation's knowledge base | Yes |
| `eval/dataset.json`, `eval/answers.json` | Written for this project | Retrieval and answer benchmarks | Yes |
| [doc2dial](https://doc2dial.github.io) (IBM, Feng et al., EMNLP 2020) | CC BY 3.0 | Retrieval benchmark on outside documents (`eval/doc2dial.py`) | No, downloaded when run |
| [MultiDoc2Dial](https://doc2dial.github.io/multidoc2dial/) (IBM, Feng et al., EMNLP 2021) | Apache-2.0 | Follow-up questions (`eval/doc2dial.py --follow-ups`) | No, downloaded when run |
| [Bitext Telco](https://huggingface.co/datasets/bitext/Bitext-telco-llm-chatbot-training-dataset) and [Customer Support](https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset) | CDLA-Sharing-1.0 | Coverage audits (`eval/coverage.py --set telco/general`), in-scope examples for the scope classifier | No, downloaded when run |
| [τ²-bench telecom](https://github.com/sierra-research/tau2-bench) (Sierra, Barres et al., 2025) | MIT | A second telecom organisation and 114 graded tasks (`eval/tau2.py`) | No, downloaded when run |
| [ABCD](https://github.com/asappresearch/abcd) (ASAPP, Chen et al., NAACL 2021) | MIT | AcmeBrands agent guidelines and 1,004 test conversations (`eval/abcd.py`), in-scope examples | No, downloaded when run |
| [RepLiQA](https://huggingface.co/datasets/ServiceNow/repliqa) (ServiceNow, Monteiro et al., NeurIPS 2024) | CC BY 4.0 | Unseen documents with unanswerable questions (`eval/repliqa.py`) | No, downloaded when run |
| [TechQA](https://huggingface.co/datasets/PrimeQA/TechQA) (IBM, Castelli et al., ACL 2020) | CDLA-Permissive-1.0 (per the archive's own licence file) | Real technical-support questions over IBM technotes (`eval/techqa.py`) | No, downloaded when run |
| [RAGTruth](https://github.com/ParticleMedia/RAGTruth) (Niu et al., ACL 2024) | MIT | Scoring the figure check (`eval/ragtruth.py`) | No, downloaded when run |
| [CLINC150](https://github.com/clinc/oos-eval) (Larson et al., EMNLP 2019) | CC BY 3.0 | Off-topic examples for the scope classifier (`eval/abstain.py`) | No, downloaded when run |
| [MASSIVE](https://github.com/alexa/massive) (Amazon, FitzGerald et al., ACL 2023) | CC BY 4.0 | Off-topic examples, and off-topic questions in Hindi, Bengali, Tamil, Telugu, Kannada, Malayalam and Urdu | No, downloaded when run |
| [Banking77](https://github.com/PolyAI-LDN/task-specific-datasets) (PolyAI, Casanueva et al., 2020) | CC BY 4.0 | Another industry's support questions, which the scope classifier must keep | No, downloaded when run |
| [TRAI QoS Regulations 2024](https://trai.gov.in/node/13235) (No. 06 of 2024) | Government of India; reproduction needs TRAI's permission, so it is cited, not copied | The help centre's regulator answer states its benchmarks in our own words | Cited only |
| Training pairs and distilled answers | Generated from the Nimbus documents by the teacher model | Fine-tuning Pleiades-Embed and Pleiades-Chat | No, `training/build/` |

Nothing downloaded is committed or redistributed; the evaluation scripts fetch copies pinned to a
commit or revision into the git-ignored `eval/external/`. Each licence was checked against the
source's own licence file or dataset card on 2026-10-12; TechQA's Hugging Face card says
Apache-2.0, but the archive's README and licence file say CDLA-Permissive-1.0, which is what applies.

## Adding your own knowledge base

Drop `.md` files into `data/`, add a display name to `SOURCE_LABELS` in `src/config.py`, and
re-run `python -m src.ingest`. Only new chunks are embedded.

### Finding what it doesn't cover

`python eval/coverage.py` samples 60 phrasings from each of the 26 intents in Bitext's telecom
support set (CDLA-Sharing-1.0, downloaded when run, never committed) and reports which section
retrieval lands on for each. Its first run on the original five documents found that nothing
answered "how do I talk to a person" (78% of those questions landed on old tickets), that
"I want compensation for the outage" missed the SLA credits because the documents only say
"refund for downtime", and that "deactivate my phone" retrieved router factory-reset steps 93% of
the time, from an ISP that sells no phones. `data/help_centre.md` was written from that list, in
the customers' own words, with every figure agreeing with the other documents; those intents now
reach the right section 65-100% of the time, and the 15-question set above is unchanged.

`--set general` runs the same audit on Bitext's 27 cross-industry customer-service intents. It found
the next gaps: "I forgot my password" retrieved the router's factory reset 85% of the time (the
documents never mention the account login), refund questions landed on payment methods, "track my
refund" on old tickets, "I want to lodge a claim" on the warranty policy, and nothing covered
registration problems or feedback. The help centre now answers each, again only with figures the
other documents already state, and the audit shows where they land (60 phrasings per intent):

| Intent | Before | After |
|---|---|---|
| recover_password | Router manual, factory reset (85%) | Account password reset (70%) |
| registration_problems | Old tickets (68%) | Sign-up problems (93%) |
| review | Talk to a person (63%) | Feedback (92%) |
| edit_account | Billing cycle date (45%) | Account password and profile (82%) |
| check_refund_policy | Warranty escalation (50%) | Refunds (60%) |
| complaint | Warranty policy (47%) | Complaints (52%) |
| get_refund / track_refund | Payment methods (25%) / old tickets (30%) | Refunds (42% / 37%) |

The first draft of the new answers created a new problem the audit caught at once: a section titled
"How do I update my account details?" pulled "I want to change my plan" away from the plan-change
answer (67% to 40%), and generic profile wording drew invoice questions too. Profile edits now sit
inside the password answer and the plan answer uses the customers' own words ("modify my plan or
contract"), so change_plan reaches it 78% of the time and every telco intent keeps its section. The
golden set moved from 13 to 14 of 15 vector-only, but only because the reworded complaint answer
left the sixth place to the RMA escalation clause, so treat that one as noise.

The help centre's regulator answer states TRAI's broadband benchmarks (QoS Regulations 2024,
No. 06 of 2024): billing complaints resolved within four weeks, adjustments within a week of
resolution, a service closed within seven working days of the request, deposits refunded within 45
days with interest on delays. Nimbus's cancellation policy used to run to the end of the billing
period, which broke the closure rule (no billing beyond seven working days of the request,
regulation 7.1.6). It now closes the connection within 7 working days, never holds closure back
for unpaid dues, and refunds the time already paid for after closure within 45 days, the deadline
regulation 7.1.7 sets for any dues owed after closure. (ISPs with at most 10,000 subscribers are
exempt; Nimbus follows the rules anyway.) The audits caught two side effects of the first wording:
the regulator answer, carrying the full closure rule, pulled "my replacement has not arrived after
three weeks" away from the escalation clause and out of the golden set's top six, and the longer
cancellation answer lost "cancel my plan" queries to the fee answer. The regulator answer now
states the rule in one clause and the cancellation answer opens with the customers' own words
("cancel, end or terminate your plan, contract or subscription"): cancel_plan reaches it 67% of
the time (58% before the change), and the golden set is unchanged at 14 of 15.

A new or changed document reaches a running deployment through `python -m src.db setup` or the
admin console's index rebuild, which copy `data/` into the organisation's documents.

## Demo script

`.\run.ps1 demo` covers the five behaviours worth showing:

1. **Cross-document synthesis.** The amber-LED question pulls the manual's LED table and the
   matching resolved ticket TKT-10231.
2. **Policy override.** "Router died 4 days after delivery" must hit the DOA clause. Answering
   from the RMA section alone tells the customer to run triage, which is wrong.
3. **Structured lookup.** Plan comparison retrieves the catalog table.
4. **Multi-document arithmetic.** "Down 3 days last month" needs the billing FAQ and the SLA
   table in the catalog together. The uptime (90.0%) and the credit row (50%) are worked out in
   code and handed to the model as an exact calculation, so it explains the result instead of
   doing the sum itself.
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
