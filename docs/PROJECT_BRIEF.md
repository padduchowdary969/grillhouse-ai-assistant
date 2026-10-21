# Grill House Ops Copilot: Project Brief

*A one-page summary for reviewers. The full detail is in the [README](../README.md),
[Architecture](ARCHITECTURE.md), [Design decisions](DESIGN_DECISIONS.md) and [Evaluation](EVALUATION.md).*

## The problem

A late-night takeaway in Manchester (open 18:00–08:00) sells through Uber Eats. Its sales, menu performance, peak
hours, conversion funnel and reviews sit in separate platform exports. Those are hard to read on a phone mid-shift,
and they're grouped by calendar day, which splits every night's trade in two. The owners wanted plain-English
answers, a forecast to plan staff and stock, and no exposure of their business data.

## What was built

An AI analyst the owners use on their phones:

- **Answers grounded in the shop's data:** a RAG assistant over reports and tables, and Text-to-SQL over a
  PostgreSQL analytics schema, always showing the SQL behind a figure.
- **Cited menu and policy search:** hybrid retrieval (BM25 + pgvector, reciprocal rank fusion).
- **Demand forecast:** LightGBM, backtested against baselines and tracked in MLflow, turned into a buns-and-patties
  order.
- **Private by design:** a phone app (PWA) served from the shop's Mac and reachable only over Tailscale. PII is
  redacted at ingestion, and the public repo runs on a synthetic dataset.

## How it works

```
Uber Eats exports / synthetic orders + Manchester weather + bank holidays
  → clean (trading nights) → PII redaction (Presidio) → PostgreSQL raw
  → dbt analytics models (16 data tests) → embeddings (pgvector) → LightGBM forecast (MLflow)
  → FastAPI: JWT roles · rate limits · /chat (RAG) · /ask/sql (Text-to-SQL) · /search (citations)
  → model layer: Qwen3 8B on Ollama (Claude via Amazon Bedrock available as an optional provider)
```

Model-written SQL passes two independent checks: a sqlglot validator (one `SELECT`, approved tables only, no writes
or system functions, row cap), then a read-only, time-limited database role.

## Results

| Measure | Result |
|---|---|
| Document search (20-question golden set) | hit@1 **1.00** hybrid vs 0.90 keyword-only |
| RAG assistant (23 questions, real and synthetic data) | **23/23** hybrid vs 16/20 keyword-only |
| Text-to-SQL (50 questions, execution match), local Qwen3 8B | 34/50, the baseline for the Claude comparison |
| Demand forecast, MAE in orders/night | LightGBM **3.52** vs 3.58 best baseline (noise floor 3.26); **3.13** vs 3.41 on rainy, event and bank-holiday nights |
| Engineering | 84 pytest tests, 16 dbt tests, CI on every push, versioned Docker images, full stack from empty in under 30 s |

Insights from a year of the shop's real Uber Eats data:
- **Peak:** Saturday night between 04:00 and 07:00.
- **Funnel:** 90% of potential customers leave before opening the menu.
- **Ratings:** slow deliveries (median 43 vs 35 minutes) go with 1–2 star ratings.
- **Add-ons:** they're under-sold, at about 0.4 per order.

## Technical scope

| Area | Used |
|---|---|
| Generative AI | RAG, hybrid retrieval, embeddings, Text-to-SQL with self-correction, grounding and refusal, prompt design |
| Evaluation | Golden sets (93 questions), execution-match scoring, hit@k and MRR, CI quality gates |
| Data engineering | PostgreSQL, pgvector, dbt, data tests, deterministic synthetic data generation |
| ML | LightGBM, rolling-origin backtesting, baselines, leakage tests, MLflow |
| Backend and security | FastAPI, JWT roles, rate limiting, AST-level SQL validation, least-privilege database role, PII redaction |
| Infrastructure | Multi-stage non-root Docker images on GHCR, Docker Compose, GitHub Actions, launchd, Tailscale Serve |

## Next

- **A LangGraph agent** for "why" questions and courier analysis.
- **Drafted actions** with human approval.
- **A fine-tuned review classifier**, compared against a TF-IDF baseline.
- **Guardrails and tracing, and a public demo** on synthetic data.

See the [roadmap](ROADMAP.md).
