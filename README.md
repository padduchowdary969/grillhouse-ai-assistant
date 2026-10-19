# grillhouse-ai-assistant
“AI business assistant for a real restaurant: analytics, forecasting, RAG chatbot”

Built for a late-night takeaway (open 18:00–08:00) that sells through Uber Eats. The scripts turn raw
Uber Eats Manager exports into clean tables, charts, a written summary and a sales forecast.

**[Read the project brief](docs/PROJECT_BRIEF.md)** for the architecture, AI techniques and deployment.

## Try it with sample data

The real business data is private and never committed. `sample_data/` holds synthetic exports in the
same layout as real Uber Eats files (made by `src/make_sample_data.py`; every number and review is invented).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GRILLHOUSE_DATA=sample_data
python src/clean_ubereats.py      # -> sample_data/clean/
python src/analyse_ubereats.py    # -> sample_data/reports/ubereats_summary.md + charts
python src/forecast_ubereats.py   # -> sample_data/reports/forecast_summary.md + chart
```

## Use your own Uber Eats data

Download these reports from Uber Eats Manager for the same date range and save them in `data/`
(git-ignored), then run the same three scripts without `GRILLHOUSE_DATA`:

| Uber Eats report | Save as |
|---|---|
| Sales over time (monthly) | `data/ubereats_monthly_2026.csv` |
| Sales leaderboard: items | `data/ubereats_items_2026.csv` |
| Sales by hour | `data/ubereats_sales_by_hour_2026.csv` |
| User conversion funnel | `data/ubereats_funnel_2026.csv` |
| Ratings | `data/ubereats_reviews_2026.csv` |

## What each script does

- `src/clean_ubereats.py`: fixes the exports (byte-order marks, float noise, duplicate item spellings),
  groups after-midnight hours into the night the shift started, and cross-checks totals between reports.
- `src/analyse_ubereats.py`: monthly trend, top items, a night-by-hour order heatmap, the customer funnel
  and customer ratings with complaint themes.
- `src/forecast_ubereats.py`: tests three simple methods on past months, forecasts the next three with the
  most accurate one (with an 80% range), and spreads each month over a typical week by night and hour.
- `src/make_sample_data.py`: regenerates the synthetic files in `sample_data/`.
- `src/chatbot.py`: answers questions in plain English using a free model that runs locally (see below).
- `src/evaluate_chatbot.py`: scores the chatbot on 11 test questions (retrieval hit and answer correctness),
  with expected answers read from the data so it works on real and sample data.

## Chatbot (free, runs on your computer)

The chatbot uses [Ollama](https://ollama.com) to run an open model locally, so it costs nothing and no
business data leaves the machine. For each question it retrieves the most relevant sections of the reports,
tables and `knowledge/*.txt` files (keyword TF-IDF search) and asks the model to answer only from them.

```bash
ollama pull qwen3:8b                     # once, about 5 GB
python src/chatbot.py                    # chat; type "quit" to stop
python src/chatbot.py "Which night is busiest?"
```

Run the clean, analyse and forecast scripts first. Set `GRILLHOUSE_MODEL` to try another Ollama model.

### Chat page and phone app

`src/web_chat.py` serves a password-protected chat page at http://localhost:8501 that can be installed on a
phone's home screen like an app. On a Mac:

1. Double-click `start_assistant.command` once to choose the password (stored in the git-ignored `.env`).
2. Double-click `install_autostart.command` so the assistant starts at login, restarts if it stops and keeps
   the Mac awake on power (`./install_autostart.command remove` undoes it).
3. With [Tailscale](https://tailscale.com) installed, run `tailscale serve --bg 8501` once. Devices on your
   tailnet then open `https://<your-mac>.<tailnet>.ts.net` and choose "Add to Home Screen".

The server listens only on this computer; Tailscale Serve is the only way in from other devices.

## Roadmap

- [x] Data cleaning
- [x] Analytics
- [x] Forecasting
- [x] Knowledge base (reports, tables, opening hours)
- [x] Chatbot (command line, local model)
- [ ] Menu with prices in the knowledge base
- [x] Chat window (web page, password, Tailscale access)
- [x] Installable phone app (home-screen web app) and auto-start
