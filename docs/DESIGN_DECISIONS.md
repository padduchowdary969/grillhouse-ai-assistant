# Design decisions

Short records of the choices that shape the system: the context, what was decided, and what it costs.

| # | Decision | Status |
|---|---|---|
| 1 | [Model the business day as a "trading night"](#1-model-the-business-day-as-a-trading-night) | Adopted |
| 2 | [Synthetic data for everything public](#2-synthetic-data-for-everything-public) | Adopted |
| 3 | [Two independent layers for model-written SQL](#3-two-independent-layers-for-model-written-sql) | Adopted |
| 4 | [Hybrid retrieval with reciprocal rank fusion](#4-hybrid-retrieval-with-reciprocal-rank-fusion) | Adopted |
| 5 | [A provider interface before choosing a model](#5-a-provider-interface-before-choosing-a-model) | Adopted |
| 6 | [Put deterministic facts in code, not in the prompt](#6-put-deterministic-facts-in-code-not-in-the-prompt) | Adopted |
| 7 | [Redact PII at ingestion](#7-redact-pii-at-ingestion) | Adopted |
| 8 | [Score Text-to-SQL by execution match](#8-score-text-to-sql-by-execution-match) | Adopted |
| 9 | [Baselines and a noise floor for the forecaster](#9-baselines-and-a-noise-floor-for-the-forecaster) | Adopted |
| 10 | [dbt without Airflow](#10-dbt-without-airflow) | Adopted |
| 11 | [Private deployment on the shop's Mac, not a cloud server](#11-private-deployment-on-the-shops-mac-not-a-cloud-server) | Adopted |
| 12 | [Ollama outside Docker on macOS](#12-ollama-outside-docker-on-macos) | Adopted |

---

### 1. Model the business day as a "trading night"

**Context.** The shop opens at 18:00 and closes at 08:00, sometimes 10:00 at weekends. Uber Eats reports by
calendar day, so an order at 04:00 on Sunday is counted as Sunday, and every night's trade is split across two
days. With that grouping, "Sunday" looked like the best day, when it was really Saturday night.

**Decision.** Every order carries a `trading_night`: the date the shift started (hours before midday belong to
the previous evening). Reports, the forecaster, the SQL tables and the assistant all use it.

**Consequence.** Night-of-week answers match how the owners think about trade. The model must be told the rule,
so it's in the Text-to-SQL business notes and in the assistant's system prompt.

### 2. Synthetic data for everything public

**Context.** The project runs on a real business, and its revenue, menu performance and customer comments are
private, but a public repo needs data that anyone can run.

**Decision.** Real exports stay in the git-ignored `data/` folder. A deterministic generator creates "Sample Grill
Kitchen": orders, items, deliveries and reviews, driven by real public weather and bank holidays plus synthetic
events and courier shortages. The patterns are hand-tuned rather than fitted to the real data, so nothing private
can leak through the generator.

**Consequence.** The demo has realistic causes for "why" questions (rain, events, shortages) and exact ground
truth for evaluation. CI checks that regenerating gives byte-identical files. The README states clearly which data
is synthetic.

### 3. Two independent layers for model-written SQL

**Context.** Text-to-SQL means running code a model wrote. Prompt injection (for example, through review text)
or a plain mistake could produce destructive or expensive queries.

**Decision.**
- **Layer 1, sqlglot:** a parsed-AST validator allows exactly one `SELECT` over six approved analytics tables. It rejects writes anywhere (including data-modifying CTEs), system catalogs and `pg_*` functions, and caps results at 200 rows.
- **Layer 2, Postgres role:** the query runs as `copilot_readonly`, which has read-only transactions, no access to `raw` and a 5-second statement timeout.

**Consequence.** Either layer alone blocks the known attacks, and both are tested. Rejections come back to the
model as error messages, so it can correct itself (up to 3 attempts).

### 4. Hybrid retrieval with reciprocal rank fusion

**Context.** Owners ask in their own words ("what do people moan about?"), but also name exact dishes. Keyword
search handles exact names well and paraphrases badly; embeddings are the reverse.

**Decision.** Rank every chunk twice, with BM25 or TF-IDF and with cosine similarity on `nomic-embed-text` vectors
(pgvector HNSW). Merge the rankings with reciprocal rank fusion (k = 60). Fall back to keywords if the embedding
model is unavailable.

**Consequence.** Measured gains:
- **RAG assistant:** 16/20 with keywords only, 20/20 with hybrid.
- **Document search:** hit@1 0.90 with keywords only, 1.00 with hybrid.

RRF needs no score calibration between the two rankings. A cross-encoder re-ranker is deferred until the corpus is
big enough to need it.

### 5. A provider interface before choosing a model

**Context.** The plan uses Claude via AWS Bedrock for quality and a local or fine-tuned model for cheap,
high-volume tasks, so they need comparing on accuracy, cost and latency.

**Decision.** `app/llm.py` gives every provider the same `complete()` call, returning text, tokens and latency.
Golden sets take a `--provider` flag.

**Consequence.** The local Qwen3 8B baseline (34/50 on Text-to-SQL) is already recorded, and Bedrock slots in
without touching callers. Routing decisions will be made from measured numbers.

### 6. Put deterministic facts in code, not in the prompt

**Context.** The 8B model answered "tonight" with a monthly forecast, added seven nights up wrong, ignored
exceptions in opening hours, and couldn't resolve "next month" without the date.

**Decision.** Compute in code whatever can be computed:
- **A dated next-7-nights forecast,** with a ready-made weekly total.
- **Today's date** in the system prompt.
- **Month names** next to `YYYY-MM`.
- **Opening hours** pinned to the instructions rather than left to retrieval.

**Consequence.** The answers became reliable: 23/23 on the assistant golden set, including tests that fail if a
monthly figure shows up for a single night. The model's job shrinks to reading and phrasing.

### 7. Redact PII at ingestion

**Context.** Review comments can contain phone numbers, emails, addresses and names. Once stored, they reach
prompts, logs and backups.

**Decision.** Presidio with spaCy's small English model, plus UK-specific recognisers for phone numbers (including
Ofcom drama ranges, which the default validator rejects), postcodes and street addresses, applied in the loader
before data reaches the database. Food words are excluded from name detection.

**Consequence.** It passed 0 false positives on the shop's 45 real comments, and catches the synthetic test cases.
A dbt test fails the build if contact details appear in `analytics.reviews`.

### 8. Score Text-to-SQL by execution match

**Context.** Comparing SQL text is useless, because many different queries are correct, and comparing model
answers by string is fragile.

**Decision.** Run the model's query and a hand-checked reference. A case passes when every reference column appears
in the result with the same values, ignoring column names, extra columns and small rounding differences.

**Consequence.** The scores reflect whether the owner would get the right numbers. The scorer has its own tests.
When a reference turns out to be wrong, `--rescore` re-checks saved SQL without new model calls.

### 9. Baselines and a noise floor for the forecaster

**Context.** A gradient-boosted model always "works"; the question is whether it beats something simpler.

**Decision.** Backtest LightGBM against "same night last week" and a "same night, 4-week mean" in a rolling 8-week
evaluation, and report the Poisson noise floor alongside.

**Consequence.** An honest result. LightGBM is near the floor overall (3.52 vs 3.58 vs a 3.26 floor), and clearly
better on rainy, event and bank-holiday nights (3.13 vs 3.41). That's where its features add information.

### 10. dbt without Airflow

**Context.** The original plan listed Airflow and dbt for ingestion.

**Decision.** Use dbt for the transformations and data tests, and a plain ordered runner (`pipelines/run_all.py`)
for orchestration, triggered by hand, Docker Compose or CI.

**Consequence.** One shop and a handful of files a month don't justify a scheduler, a metadata database and a web
UI. The runner can be swapped for a scheduler later without changing the steps.

### 11. Private deployment on the shop's Mac, not a cloud server

**Context.** The owners need the assistant on their phones from anywhere, but the data is private and the local
model needs a capable machine.

**Decision.** Run the app on the shop's Mac under launchd (start at login, restart on failure, keep awake on
power), listening on localhost only. Tailscale Serve provides HTTPS reachable only from the owners' devices. The
public demo is a separate deployment on synthetic data.

**Consequence.** It's free and private, with no inbound ports open to the internet. The trade-off is that the Mac
must stay on and online.

### 12. Ollama outside Docker on macOS

**Context.** Docker on macOS can't use the Apple GPU, so a containerised model runs on the CPU only.

**Decision.** The pipelines, database and app tooling run in Docker; Ollama runs natively on the host, and
containers reach it through `host.docker.internal`.

**Consequence.** Answers take 10–30 seconds instead of minutes. In CI, where there's no model server, search
falls back to keywords and model-graded evaluations are skipped.
