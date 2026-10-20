# Roadmap: Grill House Ops Copilot

An AI analyst for a real Manchester burger shop that answers "why" questions about sales and deliveries, then
drafts the follow-up actions. This roadmap adapts the original portfolio project plan to what is already
built and to the decisions below.

## Decisions (20 Oct 2026)

| Question | Decision |
|---|---|
| Main LLM | Claude via AWS Bedrock, routing simple high-volume tasks to a fine-tuned Llama 3 8B |
| Order-level data | Synthetic: orders, items and deliveries generated to match the real Uber Eats summaries. Real data stays as summaries, private |
| Live demo | Public, on synthetic data only. The shop's own app with real data stays private (Tailscale) |
| Time | 10+ hours a week, four phases of about two weeks |
| Frontend | Keep the existing mobile web app (PWA), served by FastAPI; no Streamlit/Next.js rewrite |
| Use in the shop | Already in daily use on the owners' phones |

## Changes from the original plan, and why

| Original plan | Adjusted | Reason |
|---|---|---|
| Airflow + dbt for ingestion | dbt + a plain scheduled pipeline (cron / GitHub Actions) | One shop, a handful of files a month: Airflow adds operations work without showing more skill |
| vLLM serving with AWQ | Fine-tune on a free Colab GPU; serve the GGUF build through Ollama; benchmark vLLM + AWQ once on Colab | vLLM and Unsloth need an NVIDIA GPU; the production Mac is Apple silicon |
| Delivery data from the platform | Synthetic `deliveries` table (promised vs actual time, status, delay reason) | The Uber Eats exports have no per-order delivery data |
| Till / POS exports | Not used | SumUp left out by choice; Uber Eats only |
| Review classifier trained on real reviews | Train on synthetic labelled reviews; test on the 229 real ratings (tags give labels) | 45 written comments are too few to fine-tune on |

## What already exists and where it goes

| Built (Oct 2026) | Becomes |
|---|---|
| `pipelines/clean_ubereats.py` | `pipelines/` ingestion step for the real summaries |
| `pipelines/make_seed_data.py`, `seed_data/` | `seed_data/` generator, extended to order level |
| `pipelines/analyse_ubereats.py` | SQL views / agent tools for charts |
| `pipelines/forecast_ubereats.py` | Baseline models in the forecaster backtest |
| `app/chatbot.py` hybrid retriever (TF-IDF + embeddings, RRF) | Retriever tool, moved to pgvector + BM25 |
| `evals/evaluate_chatbot.py` (23 questions, 23/23) | `evals/` golden set, grown to 50+, gate in CI |
| `ui/web_chat.py` + PWA + Tailscale | `ui/` + FastAPI backend; private shop deployment |

## Phase 1: Data foundation (weeks 1–2)

- [x] Repo restructure: `app/`, `ui/`, `pipelines/`, `evals/`, `seed_data/`, `tests/`, `docs/`
- [x] PostgreSQL + pgvector in Docker; schema for `orders`, `order_items`, `menu_items`, `deliveries`,
      `daily_context`, `documents`
- [x] Synthetic order-level generator matched to the real patterns: night-by-hour demand, item mix and
      prices, ratings vs delivery time, monthly trend
- [x] `daily_context` from free public sources: Manchester weather history (Open-Meteo), UK bank holidays
- [x] Synthetic weather and event effects, plus courier-delay spikes, so "why" questions have real answers
- [x] PII redaction with Presidio at ingestion (review comments)
- [x] dbt models for clean marts (`daily_sales`, `item_sales`, `delivery_performance`)
- [x] Pytest for the pipeline and generator; `docker compose up` loads everything

**Gate: data loads cleanly with one command.** ✅ Passed 20 Oct 2026: `docker compose up setup` builds the
database from empty in about 14 seconds; 19 dbt tests and 29 pytest tests pass.

Notes: the generator uses hand-tuned patterns rather than the real data as input, so nothing private can leak;
`delivery_performance` is covered by the `orders` model (lateness per order) and `daily_sales` (per night);
the read-only copilot user and its limits were set up here, ahead of Phase 2.

## Phase 2: Q&A and search → public demo (weeks 3–4)

- [x] FastAPI backend: JWT with roles, per-user rate limits, request logging; the PWA now runs on it (cookie
      sign-in, streamed /chat, private-network mode for the shop)
- [ ] Claude via Bedrock: client, model routing stub, cost and latency logging per request
- [x] Text-to-SQL tool: read-only database user, SQL allowlist (SELECT only, no system tables), query
      validation, exact-match checks in evals (50-question golden set; local Qwen3 8B: 34/50)
- [x] Retriever on pgvector + BM25 with citations (RRF fusion); menu and policy documents. Cross-encoder
      re-ranking deferred until the corpus grows
- [x] LightGBM demand forecaster on daily synthetic data, backtested against the current baselines, tracked in
      MLflow (MAE 3.52 vs 3.58 baseline; 3.13 vs 3.41 on unusual nights; noise floor 3.26)
- [x] Golden sets: 93 questions (50 Text-to-SQL, 20 document search, 23 RAG). GitHub Actions runs the pipeline,
      dbt tests, pytest and a search-quality gate on every push; model-graded evals join CI with Bedrock
- [ ] Public demo on synthetic data (Hugging Face Spaces or Render) with a spending cap and rate limit

**Gate: demo-ready — answers real questions publicly.**

## Phase 3: Agent and actions (weeks 5–6)

- [ ] LangGraph agent orchestrating the SQL, retriever, context and draft tools
- [ ] "Why" explanations combining sales, weather and delivery data
- [ ] Delivery and courier analysis with charts in answers
- [ ] Draft tool (complaints, supplier emails) with a human approval step; nothing sends unapproved
- [ ] Structured outputs with Instructor + Pydantic
- [ ] Review classifier: TF-IDF + logistic regression baseline, then Llama 3 8B QLoRA (Unsloth on Colab);
      precision, recall and cost compared; model card
- [ ] Weekly Monday brief, generated on a schedule

**Gate: safe actions — nothing sends unapproved.**

## Phase 4: Prove and ship (weeks 7–8)

- [ ] Ragas + DeepEval: faithfulness, context recall, answer relevance; results table in the README
- [ ] Model-routing comparison: Claude on Bedrock vs fine-tuned Llama 3 on accuracy, cost per query and latency
- [ ] Guardrails: NeMo Guardrails and Llama Guard on inputs (prompt injection in reviews and emails)
- [ ] JWT auth, RBAC (owner sees finances, staff see operations), audit log
- [ ] Langfuse tracing (cost, p95 latency, failed tool calls); Evidently drift reports; UI feedback button
      that writes to the eval set
- [ ] README: pitch, 30-second GIF, live demo link, 2-minute video, architecture, design decisions, eval
      table, cost per query
- [ ] Pin the repo; LinkedIn post

## Before Phase 2: Bedrock setup (owner's task)

1. AWS account with a **budget alarm** (e.g. £10/month) and an IAM user limited to Bedrock
2. Enable Anthropic Claude models in the Bedrock console for one region (e.g. `eu-west-2` London, if offered)
3. Store keys in the git-ignored `.env`; never in code

## Risks

- **Public demo cost:** every visitor's question is a paid Bedrock call, so it needs a daily cap and rate
  limits, with the local model as the fallback
- **Synthetic data credibility:** the generator must be shaped by the real summaries, and the README must say
  clearly which data is synthetic
- **Scope:** eight features plus the full senior layer is a lot; if time runs short, the review classifier and
  routing comparison move to v2
