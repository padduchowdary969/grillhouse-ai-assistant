# grillhouse-ai-assistant

[![CI](https://github.com/padduchowdary969/grillhouse-ai-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/padduchowdary969/grillhouse-ai-assistant/actions/workflows/ci.yml)
“AI business assistant for a real restaurant: analytics, forecasting, RAG chatbot”

Built for a late-night takeaway (open 18:00–08:00) that sells through Uber Eats. The scripts turn raw
Uber Eats Manager exports into clean tables, charts, a written summary and a sales forecast.

**[Read the project brief](docs/PROJECT_BRIEF.md)** for the architecture, AI techniques and deployment.

## Quick start (synthetic demo data)

The shop's real data is private and never committed. `seed_data/` holds a synthetic dataset for "Sample Grill
Kitchen": about 7,800 orders with basket items and deliveries, driven by real Manchester weather and UK bank
holidays plus synthetic events and courier-shortage weeks, and Uber Eats-style summary exports aggregated from
those orders. Every order, menu item and review is invented.

```bash
cp .env.example .env                    # then set the passwords
docker compose up setup                 # PostgreSQL + pgvector, synthetic data, dbt models and tests
```

Or without Docker for the Python side:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db                 # database only
python -m pipelines.run_all             # seed data -> clean -> reports -> database -> dbt
python -m pytest                        # 74 tests
```

### Repository layout

```
pipelines/   ingestion: seed-data generator, weather/holidays, cleaning, PII redaction, DB load, reports, forecast
dbt/         analytics models (orders, order_items, daily_sales, item_sales_monthly, menu_items, reviews) + tests
db/          schema and database roles (owner vs read-only copilot user)
app/         chatbot: hybrid retrieval and answers; shared config
ui/          password-protected chat page, installable on phones
evals/       chatbot test set (retrieval hit + answer correctness)
tests/       pytest: redaction, seed-data consistency, cleaning, retrieval, database permissions
seed_data/   synthetic dataset (public)
data/        the shop's real exports (git-ignored, private)
```

### Data model

| Table (schema `analytics`) | One row per |
|---|---|
| `orders` | order, with promised vs actual delivery time, lateness and delay reason |
| `order_items` | item in an order |
| `daily_sales` | trading night (18:00 to closing), with weather, bank holiday, event and courier-shortage flags |
| `item_sales_monthly` | item per month |
| `menu_items` | dish, with price, allergens, dietary tags and spice level |
| `reviews` | rating, with the comment PII-redacted at ingestion (Presidio) |

The copilot connects as `copilot_readonly`: it can only `SELECT` from `analytics`, can't see `raw`, runs in
read-only transactions and is cut off after 5 seconds.

## Copilot API (Phase 2, in progress)

```bash
uvicorn app.api:app --port 8000          # interactive docs at http://localhost:8000/docs
```

| Endpoint | What it does |
|---|---|
| `POST /auth/token` | Sign in; returns a JWT carrying the role (owner or staff) |
| `POST /ask/sql` | Text-to-SQL: question → validated query → answer, with the SQL shown (rate-limited) |
| `POST /search` | Menu and policy search (pgvector + BM25, reciprocal rank fusion) with citations |
| `POST /sql` | Run a validated read-only query directly (owners only) |
| `GET /health` | Database check |

Every query is parsed with sqlglot and must be a single `SELECT` over the six analytics tables (no system
tables, no `pg_*` functions, no writes hidden in CTEs, 200-row cap), and then runs as the read-only database user.

### Evaluation so far

| What | Score |
|---|---|
| Text-to-SQL golden set (20 questions, execution match), local Qwen3 8B | 13/20 (65%) |
| Text-to-SQL, Claude via Bedrock | pending AWS setup |
| RAG chatbot (23 questions), hybrid search | 23/23 on real and synthetic data |
| RAG chatbot, keyword search only | 16/20 on the plain + casual sets |

### Demand forecast

`pipelines/forecast_demand.py` forecasts orders for the next 7 nights with LightGBM, backtested over 8 weeks
(rolling origin) and tracked in MLflow, then converts the forecast into buns and patties to order.

| Model | Mean abs. error (orders/night) | On rainy, event and bank-holiday nights |
|---|---|---|
| LightGBM | **3.52** | **3.13** |
| Same night, 4-week average | 3.58 | 3.41 |
| Same night last week | 4.57 | 4.18 |

Pure chance (Poisson noise at ~16 orders a night) accounts for about 3.26, so on ordinary nights the strong
models are near the limit; LightGBM's gain comes from weather and calendar context.

## Use your own Uber Eats data

Download these reports from Uber Eats Manager for the same date range and save them in `data/`
(git-ignored), then run `pipelines.clean_ubereats`, `pipelines.analyse_ubereats` and `pipelines.forecast_ubereats`
without `GRILLHOUSE_DATA`:

| Uber Eats report | Save as |
|---|---|
| Sales over time (monthly) | `data/ubereats_monthly_2026.csv` |
| Sales leaderboard: items | `data/ubereats_items_2026.csv` |
| Sales by hour | `data/ubereats_sales_by_hour_2026.csv` |
| User conversion funnel | `data/ubereats_funnel_2026.csv` |
| Ratings | `data/ubereats_reviews_2026.csv` |

## What each script does

- `pipelines/clean_ubereats.py`: fixes the exports (byte-order marks, float noise, duplicate item spellings),
  groups after-midnight hours into the night the shift started, and cross-checks totals between reports.
- `pipelines/analyse_ubereats.py`: monthly trend, top items, a night-by-hour order heatmap, the customer funnel
  and customer ratings with complaint themes.
- `pipelines/forecast_ubereats.py`: tests three simple methods on past months, forecasts the next three with the
  most accurate one (with an 80% range), and spreads each month over a typical week by night and hour.
- `pipelines/make_seed_data.py`: generates the synthetic order-level dataset and the summary exports in `seed_data/`.
- `pipelines/fetch_context.py`: downloads Manchester weather (Open-Meteo) and UK bank holidays (gov.uk).
- `pipelines/redact.py`: masks names, phone numbers, emails, postcodes and addresses (Presidio + UK patterns).
- `pipelines/load_db.py`: loads `seed_data/` into PostgreSQL with redaction and integrity checks.
- `pipelines/run_all.py`: runs the whole pipeline in order.
- `app/chatbot.py`: answers questions in plain English using a free model that runs locally (see below).
- `evals/evaluate_chatbot.py`: scores the chatbot on 20 test questions (11 plainly worded, 9 in casual wording)
  for retrieval hit and answer correctness, with expected answers read from the data so it works on real and
  sample data.

## Chatbot (free, runs on your computer)

The chatbot uses [Ollama](https://ollama.com) to run an open model locally, so it costs nothing and no
business data leaves the machine. For each question it retrieves the most relevant sections of the reports,
tables and `knowledge/*.txt` files with **hybrid search** (TF-IDF keywords plus `nomic-embed-text`
embeddings, merged by reciprocal rank fusion) and asks the model to answer only from them.

```bash
ollama pull qwen3:8b                     # once, about 5 GB
ollama pull nomic-embed-text             # once, about 270 MB (search by meaning)
python -m app.chatbot                    # chat; type "quit" to stop
python -m app.chatbot "Which night is busiest?"
```

Run the clean, analyse and forecast scripts first. Set `GRILLHOUSE_MODEL` to try another Ollama model, or
`GRILLHOUSE_SEARCH=keyword` to use keyword search only.

### Chat page and phone app

`ui/web_chat.py` serves a password-protected chat page at http://localhost:8501 that can be installed on a
phone's home screen like an app. On a Mac:

1. Double-click `start_assistant.command` once to choose the password (stored in the git-ignored `.env`).
2. Double-click `install_autostart.command` so the assistant starts at login, restarts if it stops and keeps
   the Mac awake on power (`./install_autostart.command remove` undoes it).
3. With [Tailscale](https://tailscale.com) installed, run `tailscale serve --bg 8501` once. Devices on your
   tailnet then open `https://<your-mac>.<tailnet>.ts.net` and choose "Add to Home Screen".

The server listens only on this computer; Tailscale Serve is the only way in from other devices.

## Roadmap

Done (v1, in daily use at the shop): data cleaning, analytics, forecasting, hybrid-search RAG chatbot on a
local model, automated evals (23/23), installable phone app with password and private Tailscale access.

Next: the **Ops Copilot**: Text-to-SQL, a LangGraph agent for "why" questions, courier analysis, a
fine-tuned review classifier, actions with human approval, evals in CI, guardrails and a public demo on
synthetic data. See **[docs/ROADMAP.md](docs/ROADMAP.md)** for the phased plan.
