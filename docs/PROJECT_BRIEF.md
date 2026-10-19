# Grill House AI Assistant: Project Brief

## 1. Summary

A **privately hosted AI business assistant** for a late-night takeaway (open 18:00–08:00) that sells through
Uber Eats. It turns raw platform exports into analytics and a sales forecast, then answers the owners'
questions in plain English through a **retrieval-augmented generation (RAG)** chatbot. The chatbot runs on a
**local open-source large language model**, so there are no API costs and the business data never leaves the
owner's machine. The owners use it as an **installable mobile web app** from anywhere.

**Stack:** Python · pandas · NumPy · matplotlib · Ollama · Qwen3 8B · TF-IDF retrieval · HTTP server · PWA ·
Tailscale · macOS launchd · Git/GitHub

## 2. Problem

- **Scattered data:** sales, menu performance, peak hours, customer funnel and reviews sit in separate
  Uber Eats reports, and are hard to read on a phone mid-shift.
- **Overnight trading:** an order at 04:00 on Sunday belongs to Saturday night's shift, but the platform
  groups it by calendar day, which distorts every daily view.
- **Constraints:** no budget for paid AI APIs, and business data must stay private.

## 3. Architecture

```
 Uber Eats exports (5 CSVs)
        │
        ▼
 ① Data pipeline (ETL) ── cleaning, validation, feature engineering
        │
        ├──► ② Analytics ── charts + markdown report
        ├──► ③ Forecasting ── backtested model + prediction intervals
        ▼
 ④ Knowledge base ── reports, tables, shop info → chunked documents
        │
        ▼
 ⑤ Retriever (TF-IDF) ── top-k relevant chunks per question
        │
        ▼
 ⑥ LLM inference (Qwen3 8B via Ollama, local) ── grounded answer, streamed
        │
        ▼
 ⑦ Web app (PWA) ── password auth → Tailscale Serve (HTTPS) → owners' phones
```

## 4. Components

### ① Data pipeline (ETL): [`src/clean_ubereats.py`](../src/clean_ubereats.py)

- **Inputs:** five Uber Eats Manager exports (monthly sales, item leaderboard, sales by hour, conversion
  funnel, ratings).
- **Cleaning:** removes byte-order marks and floating-point noise, normalises column names, merges duplicate
  item spellings, and drops internal IDs from the ratings data (data minimisation).
- **Feature engineering:** adds a **"trading night"** feature that assigns after-midnight orders to the shift
  that started the evening before, and flags orders outside opening hours.
- **Validation:** **data-quality assertions** that the monthly, hourly and item reports agree on totals
  (to within 1%).

### ② Analytics: [`src/analyse_ubereats.py`](../src/analyse_ubereats.py)

- **What it covers:** menu concentration (Pareto: 9 of 69 items make 80% of sales), a night-by-hour demand
  heatmap, conversion funnel rates and ratings analysis.
- **Complaint themes:** grouped from review text with rule-based keyword classification.
- **Charts:** follow accessibility rules, e.g. no misleading log-scale bars and direct labels on values.

### ③ Forecasting: [`src/forecast_ubereats.py`](../src/forecast_ubereats.py)

- **Model selection:** three baseline models (naive, moving average, linear trend) are compared by
  **rolling-origin backtesting** with MAE and MAPE. The best one, a 3-month moving average, misses by about
  12% a month on average.
- **Uncertainty:** an **80% prediction interval** that widens with forecast distance.
- **Typical week:** the monthly forecast is split into expected orders per night and per hour, for staffing
  and prep.
- **Known limit:** with one settled year of data, the model can't learn seasonal patterns yet.

### ④–⑥ RAG chatbot: [`src/chatbot.py`](../src/chatbot.py)

- **Knowledge base:** markdown reports split into chunks by heading, plus serialised data tables (items,
  months, night × hour orders, review comments, forecast week) and shop facts. About 13 chunks.
- **Retrieval:** **sparse retrieval** using TF-IDF scores with light stemming and stop-word removal. Chunk
  titles are weighted double, and it returns the **top-k = 5** chunks per question. Shop facts that every
  answer needs (opening hours) are pinned into the **system prompt** instead.
- **Generation:** Qwen3 8B, an open-weights model with about 8 billion parameters, **4-bit quantized**
  (about 5 GB). It runs locally through Ollama on Apple-silicon GPU acceleration.
- **Settings:** temperature 0.2, a 16K-token **context window**, reasoning ("thinking") mode turned off to cut
  response time, and answers **streamed** as they're generated.
- **Grounding and hallucination control:** the system prompt tells the model to answer only from the
  retrieved context and to say "I don't have that information" otherwise.
- **Prompt engineering:** the instructions require mentioning exceptions and quoting table values exactly.
  Tables carry explicit labels (e.g. annual totals vs per-night forecasts) so the small model doesn't mix up
  units.
- **Conversation memory:** a short rolling window of past turns supports follow-up questions. The retrieved
  facts aren't kept in that history, which saves context space.
- **Evaluation:** an automated test set ([`src/evaluate_chatbot.py`](../src/evaluate_chatbot.py)) of 11
  questions covering facts, timing, forecasts, reviews and **unanswerable** questions (to check the model
  refuses instead of guessing). Each case scores **retrieval hit** (was the right chunk retrieved?) and
  **answer correctness** (does the reply contain the expected values, read from the data so the same tests run
  on real and synthetic data?). Current score: **11/11 retrieval and 11/11 answers** on both datasets, median
  response time 10–14 s. One known weakness of a small model remains: occasional overconfidence on
  "sometimes" facts.

### ⑦ Deployment: [`src/web_chat.py`](../src/web_chat.py), [`install_autostart.command`](../install_autostart.command)

| Layer | What it does |
|---|---|
| **Local inference server** | Ollama hosts the LLM on the owner's MacBook (Apple M5, 16 GB); no cloud GPU or paid API |
| **App server** | Python threaded HTTP server; streaming responses; one request to the model at a time (concurrency lock) |
| **Front end** | Mobile-first chat UI built as a **Progressive Web App**: manifest, icons and service worker, so it installs on the home screen and runs full screen; supports dark mode |
| **Authentication** | Password with constant-time comparison, HttpOnly/SameSite session cookies, and a lockout after repeated failures; the secret lives in a git-ignored `.env` |
| **Network security** | Server listens on localhost only. **Tailscale Serve** provides HTTPS and access only from devices on the private network; the server also refuses any address outside localhost and Tailscale |
| **Process management** | A macOS **launchd** agent starts it at login, restarts it if it crashes, and keeps the Mac awake on power |
| **Privacy by design** | Real data is git-ignored; a **synthetic data generator** ([`src/make_sample_data.py`](../src/make_sample_data.py)) makes the public repo reproducible without exposing the business |

**Why not Docker or a paid API?** On macOS, Docker containers can't use the Apple GPU, so inference would be
several times slower. A local model kept the project free and private.

## 5. Results

- **Data:** a year of trading cleaned and checked: over 6,000 orders and 229 customer ratings.
- **Insights the owners can act on:**
  - Saturday night from 04:00 to 07:00 is the peak.
  - 90% of potential customers leave before opening the menu.
  - Slow deliveries (median 43 minutes vs 35) go with 1–2 star ratings.
  - Add-ons are under-sold, at about 0.4 per order.
- **Daily use:** the owners get answers in plain English in 10–30 seconds on their phones, at no running cost.

## 6. AI and ML concepts used

Retrieval-augmented generation (RAG) · TF-IDF sparse retrieval · top-k retrieval · chunking · open-weights
LLM · 4-bit quantization · local / on-device inference · context window · system prompt · prompt engineering ·
grounding · hallucination mitigation · evaluation (retrieval hit rate, answer accuracy) · temperature · response streaming · conversational memory ·
backtesting · prediction intervals · feature engineering · synthetic data · data minimisation

## 7. Next steps

- **Menu:** add the menu with prices to the knowledge base, using a vision model to read a photo of the menu.
- **Better search:** move to **dense retrieval** with an embedding model such as `nomic-embed-text` for
  meaning-based matching.
- **Better forecasts:** switch to daily data to capture weekly and seasonal patterns.
- **Richer evaluation:** more test cases and an LLM acting as judge for open-ended answers.
- **Server option:** a Docker image for running it on a server.

## Try it

The repo runs end to end on synthetic data. See the [README](../README.md).
