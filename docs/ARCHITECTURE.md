# Architecture

How the Grill House Ops Copilot is built, from raw exports to an answer on a phone.

- [Process map](#process-map)
- [System components](#system-components)
- [Data pipeline](#data-pipeline)
- [Data model](#data-model)
- [Request path](#request-path)
- [Model layer](#model-layer)
- [Security layers](#security-layers)
- [Deployment](#deployment)
- [Continuous integration](#continuous-integration)

## Process map

The end-to-end lifecycle. Each stage has an owner module and a check that has to pass before the next one runs.

```mermaid
flowchart LR
    A["1 · Collect<br/>Uber Eats exports<br/>weather · holidays"] --> B["2 · Prepare<br/>clean · trading nights<br/>PII redaction"]
    B --> C["3 · Store<br/>Postgres raw schema<br/>integrity checks"]
    C --> D["4 · Model<br/>dbt marts + tests<br/>embeddings · forecast"]
    D --> E["5 · Serve<br/>FastAPI · Text-to-SQL<br/>RAG · search"]
    E --> F["6 · Evaluate<br/>golden sets<br/>CI quality gates"]
    F --> G["7 · Deploy<br/>launchd + Tailscale<br/>(private) · demo (public)"]
    G -. "feedback, new questions" .-> F
    F -. "regressions block the merge" .-> D
```

| Stage | Modules | Gate |
|---|---|---|
| 1. Collect | `pipelines/fetch_context.py`, `pipelines/make_seed_data.py`, Uber Eats exports in `data/` | Weather and holiday downloads cached; seed generator is deterministic (CI fails on drift) |
| 2. Prepare | `pipelines/clean_ubereats.py`, `pipelines/redact.py` | Totals cross-checked across reports; contact details never stored |
| 3. Store | `pipelines/load_db.py`, `db/schema.sql` | Order totals reconcile with line items; constraints on every table |
| 4. Model | `dbt/`, `app/documents.py`, `pipelines/forecast_demand.py` | 16 dbt data tests; forecaster backtested against baselines |
| 5. Serve | `app/api.py`, `app/text_to_sql.py`, `app/sql_tool.py`, `app/chatbot.py` | Query validation and a read-only role on every query |
| 6. Evaluate | `evals/` | Search-quality floors enforced in CI; model evals scored by execution match |
| 7. Deploy | `scripts/macos/`, `docker-compose.yml`, `.github/workflows/ci.yml` | One-command rebuild; CI on every push |

## System components

```mermaid
flowchart TB
    subgraph ui["ui/ · Phone app"]
        pwa["index.html (vanilla JS PWA)<br/>manifest · service worker · icons"]
    end

    subgraph app["app/ · Backend"]
        api["api.py<br/>FastAPI · JWT roles · rate limit · request log · network allowlist"]
        chatbot["chatbot.py<br/>RAG over reports and tables · dated 7-night forecast"]
        t2s["text_to_sql.py<br/>schema + rules + examples → SQL → answer"]
        sqltool["sql_tool.py<br/>sqlglot validation · read-only execution"]
        docs["documents.py<br/>chunking · BM25 + pgvector · RRF · citations"]
        llm["llm.py<br/>provider interface (local · bedrock)"]
        config["config.py<br/>.env · connection strings"]
    end

    subgraph pipelines["pipelines/ · Batch jobs"]
        run_all["run_all.py"]
        seed["make_seed_data.py"]
        ctx["fetch_context.py"]
        clean["clean_ubereats.py"]
        redact["redact.py"]
        load["load_db.py"]
        fc["forecast_demand.py"]
    end

    subgraph stores["Stores"]
        pg[("PostgreSQL + pgvector")]
        mlflow[("MLflow · SQLite")]
        files[("seed_data/ · data/")]
    end

    ollama["Ollama<br/>qwen3:8b · nomic-embed-text"]

    pwa --> api
    api --> chatbot & t2s & docs & sqltool
    t2s --> sqltool
    t2s --> llm
    chatbot --> ollama
    llm --> ollama
    docs --> ollama
    sqltool --> pg
    docs --> pg
    run_all --> seed & clean & load & fc
    ctx --> files
    seed --> files
    clean --> files
    load --> redact
    load --> pg
    fc --> pg
    fc --> mlflow
```

| Component | Responsibility | Key design points |
|---|---|---|
| `app/api.py` | HTTP boundary | JWT carries role and session id; cookie sign-in for the PWA, bearer for API clients; sliding-window rate limit; fail-closed network allowlist; JSON request log with latency and model tokens |
| `app/text_to_sql.py` | Question → SQL → answer | Live schema read from `information_schema`; business rules (trading nights, weekends, money before commission); JSON-constrained output; up to 3 attempts with the database error fed back |
| `app/sql_tool.py` | Safe execution | AST checks on top of database permissions; schema-qualifies tables; 200-row cap; errors returned to the model rather than raised |
| `app/documents.py` | Cited search | One chunk per markdown section; HNSW cosine index; BM25 and dense rankings fused with RRF (k = 60); falls back to BM25 if embeddings are missing |
| `app/chatbot.py` | Assistant used by the phone app | Hybrid retrieval over reports and tables; today's date and opening hours pinned in the system prompt; dated next-7-nights forecast built per question |
| `app/llm.py` | Model abstraction | Same `complete()` interface for every provider, returning tokens and latency, so tasks can be routed and compared |
| `pipelines/forecast_demand.py` | Demand forecast | Features only look 7+ nights back, so a full week is forecastable; Poisson objective; rolling-origin backtest; MLflow tracking |

## Data pipeline

`python -m pipelines.run_all` (or `docker compose up setup`) runs every step in order and stops at the first failure.

```mermaid
flowchart LR
    ctx["Open-Meteo weather<br/>gov.uk bank holidays"] --> seed
    seed["make_seed_data<br/>orders · items · deliveries<br/>reviews · menu · policies"] --> exports["Uber Eats-style<br/>summary exports"]
    exports --> clean["clean_ubereats<br/>BOM · float noise · spellings<br/>trading nights · cross-checks"]
    clean --> reports["analyse + forecast<br/>charts · markdown reports"]
    seed --> load["load_db<br/>Presidio redaction<br/>COPY into raw.*<br/>integrity checks"]
    clean --> load
    load --> index["documents.index<br/>chunk · embed"]
    index --> dbt["dbt build<br/>7 models · 16 tests"]
    load --> dbt
    dbt --> fc["forecast_demand<br/>LightGBM · MLflow<br/>buns and patties plan"]
```

How the synthetic data is generated:

1. **Demand per night** = plateau × launch ramp and monthly drift × night-of-week weight × rain (+15%) and heat
   (−10%) × bank holiday (+20%) × synthetic events (+25–40%). The order count is Poisson around that.
2. **Each order** gets a time from the shift's hourly profile (peak 03:00–06:00), a basket sampled by item
   popularity, and a channel (2% pickup).
3. **Each delivery** gets a promised time (longer at weekend peaks and in rain) and an actual time with delays from
   rain, peaks and three synthetic courier-shortage weeks. More than 10 minutes over is "late", with a reason.
4. **Ratings** are drawn for 1 in 25 recent orders, and late deliveries are rated worse. A few contain fake
   personal details and prompt-injection attempts, as test cases.
5. **The Uber Eats-style summary exports** are aggregated from those same orders, quirks included, so reports and
   SQL answers agree to the penny.

The patterns are hand-tuned, not fitted to the shop's real data, so nothing private can leak through the generator.

## Data model

`raw` holds tables as loaded. `analytics` holds the dbt models, which are the only tables the copilot can query.

```mermaid
erDiagram
    orders ||--|{ order_items : contains
    menu_items ||--o{ order_items : "sold as"
    orders ||--o| reviews : "may receive"
    daily_sales ||--|{ orders : "aggregates (trading_night)"

    orders {
        text order_id PK
        timestamp placed_at
        date trading_night
        text night_of_week
        int hour
        text channel "delivery | pickup"
        numeric total "GBP before commission"
        text status "completed | cancelled"
        int promised_minutes
        int actual_minutes
        int minutes_late
        bool is_late "more than 10 min"
        text delay_reason
    }
    order_items {
        text order_id FK
        text item FK
        text category
        int quantity
        numeric unit_price
        numeric line_total
    }
    menu_items {
        text item PK
        text category
        numeric price
        text allergens
        text dietary_tags
        smallint spice_level
    }
    daily_sales {
        date trading_night PK
        int orders
        numeric sales
        int late_deliveries
        bool is_rainy
        numeric temp_max_c
        bool is_bank_holiday
        text event
        bool courier_shortage
    }
    reviews {
        text order_id
        int rating
        text tags
        text comment "PII-redacted"
    }
    item_sales_monthly {
        date month
        text item
        text category
        int quantity
        numeric sales
    }
    documents {
        bigint id PK
        text source
        text heading
        text content
        vector embedding "768-d, HNSW cosine"
    }
```

`daily_sales` is built from a calendar, so nights with no orders appear as zeros. That matters for "why did
orders drop?" questions.

## Request path

The Text-to-SQL path is shown in the [README](../README.md#how-a-question-is-answered). The phone app's assistant
works like this:

```mermaid
sequenceDiagram
    autonumber
    actor User as Owner (phone)
    participant TS as Tailscale Serve (HTTPS)
    participant API as FastAPI /chat
    participant R as Retriever
    participant M as Qwen3 8B (Ollama)

    User->>TS: "What should I prep for Saturday night?"
    TS->>API: Proxied to 127.0.0.1:8501
    API->>API: Network allowlist · cookie JWT · rate limit
    API->>R: Rank knowledge sections (TF-IDF + embeddings, RRF)
    R-->>API: Top 5 sections + dated 7-night forecast
    API->>M: System rules + today's date + hours + facts + recent turns
    M-->>API: Tokens (streamed)
    API-->>User: Streamed answer, kept in this session's history
```

## Model layer

| Task | Today | Planned |
|---|---|---|
| Assistant answers, Text-to-SQL | Qwen3 8B, 4-bit, local (Ollama), thinking off, temperature 0–0.2 | Claude via AWS Bedrock; route simple, high-volume tasks to a local or fine-tuned model |
| Embeddings | nomic-embed-text (768-d), with task prefixes | same |
| Review classification | keyword themes | TF-IDF + logistic regression baseline vs Llama 3 8B QLoRA (Colab GPU), served through Ollama |
| Forecasting | LightGBM (Poisson objective) | same, with daily real data if available |

Every provider returns tokens and latency, so the routing comparison (accuracy, cost per query, p95 latency)
runs on the same golden sets.

## Security layers

Defence in depth for model-written SQL. Each layer works on its own, so a miss in one is caught by the next.

```mermaid
flowchart TB
    q["Model-written SQL"] --> v1{"sqlglot parse:<br/>exactly one statement?"}
    v1 -- no --> rej["Rejected · error returned to the model"]
    v1 -- yes --> v2{"SELECT only?<br/>no writes anywhere, incl. CTEs"}
    v2 -- no --> rej
    v2 -- yes --> v3{"Only the 6 analytics tables?<br/>no catalogs, no pg_* functions"}
    v3 -- no --> rej
    v3 -- yes --> cap["Schema-qualify · cap at 200 rows"]
    cap --> role["Run as copilot_readonly:<br/>no access to raw · read-only transactions · 5 s timeout"]
    role --> ok["Result"]
```

| Concern | Control |
|---|---|
| Destructive or exfiltrating SQL | sqlglot AST validation + read-only role without access to `raw` |
| Runaway queries | `statement_timeout = 5s` on the role, 200-row cap |
| Personal data | Presidio + UK recognisers at ingestion; dbt test fails if contact details appear |
| Account access | Constant-time password check, lockout after 10 failures, JWT with expiry, HttpOnly + SameSite cookies |
| Network exposure | Server binds to localhost; Tailscale Serve is the only way in; fail-closed allowlist |
| Secrets | `.env` git- and docker-ignored; CI uses throwaway values |
| Prompt injection | Synthetic test cases in reviews today; NeMo Guardrails / Llama Guard in Phase 4 |

## Deployment

Two deployments share one codebase.

```mermaid
flowchart LR
    subgraph private["Private · the shop (real data)"]
        phones["Owners' phones<br/>PWA on home screen"] -- "Tailscale (WireGuard)" --> serve["Tailscale Serve<br/>HTTPS, tailnet only"]
        serve --> uv["uvicorn app.api:app<br/>127.0.0.1:8501<br/>private-network mode"]
        uv --> ol["Ollama on the Mac"]
        uv --> real[("data/ · real exports<br/>git-ignored")]
        ld["launchd agent<br/>start at login · restart · keep awake"] -. manages .-> uv
    end

    subgraph public["Public · demo (synthetic data)"]
        visitor["Recruiters · reviewers"] --> host["Hosted container (planned)<br/>rate limits + spending cap"]
        host --> pgd[("Postgres + pgvector<br/>seed_data/")]
        host --> br["Claude via Bedrock"]
    end
```

**Private deployment (macOS)**

1. Double-click `scripts/macos/start_assistant.command` once to choose the password (saved in `.env`).
2. Double-click `scripts/macos/install_autostart.command`. A launchd agent starts the app at login, restarts it
   if it stops, and keeps the Mac awake on power. `scripts/macos/install_autostart.command remove` undoes it.
3. Run `tailscale serve --bg 8501` once. Devices signed in to the same tailnet open
   `https://<mac-name>.<tailnet>.ts.net` and add it to the home screen.

**Local development:** `docker compose up -d db`, then `uvicorn app.api:app --port 8000`.

## Continuous integration

```mermaid
flowchart LR
    push["git push / pull request"] --> svc["Service: Postgres 17 + pgvector"]
    svc --> roles["db/init/01_roles.sh<br/>roles and schemas"]
    roles --> deps["pip install -r requirements.txt"]
    deps --> build["pipelines.run_all<br/>seed → clean → load → dbt tests → LightGBM"]
    build --> drift{"seed_data/ identical<br/>to the committed copy?"}
    drift -- no --> fail["❌ fail"]
    drift -- yes --> tests["pytest: 81 tests incl.<br/>SQL guard, API auth, redaction,<br/>search-quality floors"]
    tests --> pass["✅ pass"]
```

CI has no model server, so search is gated on its keyword-only scores, and the model-graded evaluations
(Text-to-SQL, assistant) run locally until the Bedrock provider is in place.
