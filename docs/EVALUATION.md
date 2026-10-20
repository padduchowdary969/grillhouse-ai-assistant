# Evaluation

Every model-facing part of the copilot has a golden set, a scorer and a recorded result. Numbers below are from
the synthetic demo dataset unless marked otherwise, measured on 20 October 2026.

| Golden set | Size | What is scored | Needs a model | In CI |
|---|---|---|---|---|
| [`evals/sql_golden.jsonl`](../evals/sql_golden.jsonl) | 50 | Text-to-SQL, execution match against a reference query | yes | not yet (Bedrock) |
| [`evals/search_golden.jsonl`](../evals/search_golden.jsonl) | 20 | Document search: hit@1, hit@3, MRR | no | ✅ quality floor |
| [`evals/evaluate_chatbot.py`](../evals/evaluate_chatbot.py) | 23 | RAG assistant: retrieval hit and expected facts in the answer | yes | not yet |

## Text-to-SQL

**Method.** Each case is a question plus a hand-written reference query. The model's query runs through the same
validator and read-only role as production, and passes when every column of the reference result appears in its
result with the same values. Column names, extra columns and rounding differences up to 0.5% are ignored. When
the reference returns one row, only the model's first row is compared. The scorer has its own tests
([`tests/test_sql_scoring.py`](../tests/test_sql_scoring.py)), so it is neither too strict nor too lenient.

**Coverage.** The 50 cases cover sales and time periods, menu and allergens, night-of-week patterns, weather,
events and bank holidays, delivery lateness and delay reasons, cancellations, ratings and order values.

| Model | Correct | Median latency | Needed retries |
|---|---|---|---|
| Qwen3 8B, 4-bit, local (Ollama) | **34/50 (68%)** | 8 s | 6 |
| Claude via AWS Bedrock | *in progress* | | |

**Where the local model fails (16 cases)**, grouped by cause:

| Cause | Cases | Example |
|---|---|---|
| Calendar meaning | 3 | "Christmas night 2025" queried 24 December; "before midnight" used a 23:00 cut-off; "best month" grouped by order timestamp instead of trading night |
| Wrong grain or grouping | 5 | "busiest hour" looked for an hour column in the nightly table; "event nights vs other nights" grouped by each event's name |
| Missing a filter or definition | 5 | counted cancelled orders as orders; "cancelled orders by reason" filtered to completed orders; "late rate" computed from minutes instead of a count |
| Multi-table questions | 3 | "average rating for late deliveries" needs reviews joined to orders; "top 5 burgers in September" gave up after 3 attempts |

These are the failure modes the [business rules](../app/text_to_sql.py) already describe, which suggests a
model-capacity limit rather than missing context. The routing comparison with Claude will test that.

**Golden-set maintenance.** One reference was too narrow: the bank-holiday question's reference silently limited
itself to one year. It was corrected, and `python -m evals.evaluate_sql --rescore` re-checked the saved model SQL
without new model calls (33 → 34 correct).

## Document search

**Method.** 20 questions, each with the menu or policy section that should come back first. Scored by hit@1,
hit@3 and mean reciprocal rank over the top 5.

| Search | hit@1 | hit@3 | MRR |
|---|---|---|---|
| Keyword only (BM25) | 0.90 | 1.00 | 0.95 |
| **Hybrid (BM25 + pgvector, RRF)** | **1.00** | **1.00** | **1.00** |

Keyword search misses two questions where wording and content differ. *"Can coeliacs eat the fries?"* ranks the
Sides menu first because "fries" dominates, while the answer is in the allergen policy (shared fryers).
*"What drinks can I order?"* matches the supplier terms on "order". Embeddings fix both.

**CI gate.** [`tests/test_search_quality.py`](../tests/test_search_quality.py) fails the build if keyword hit@1
drops below 0.85 or hit@3 below 1.00, and, where embeddings exist, if hybrid hit@1 drops below 0.95.

## RAG assistant

**Method.** 23 questions in three sets: 11 plainly worded, 9 in casual wording ("what do people moan about?",
"which grub barely sells?"), and 3 relative-date questions ("tonight", "this week"). Each case checks that the right
knowledge section was retrieved and that the answer contains the expected facts, read from the data so the set
works on real and synthetic data alike. Unanswerable questions ("who's our accountant?") must be refused.

| Search | Plain | Casual | Dated | Total |
|---|---|---|---|---|
| Keyword only | 11/11 | 5/9 | n/a | 16/20 |
| **Hybrid** | **11/11** | **9/9** | **3/3** | **23/23** |

Hybrid scores 23/23 on both the shop's real data and the synthetic data. Fixes found by this set, all kept as test
cases:
- **Today's date:** the model didn't know it, so "next month" was ambiguous. It now gets the date with every question.
- **Month names:** "January" didn't match `2026-01`. The monthly table now carries month names.
- **"Tonight" vs monthly totals:** "tonight" was answered with a monthly total. Answers now use a dated 7-night forecast, and the tests fail if a monthly figure appears.
- **Weekly totals:** the model added nights up wrong, so the 7-night total is now computed in code.

## Demand forecast

**Method.** Rolling-origin backtest over the last 8 weeks: each week is predicted from data before it only, and
every history feature looks at least 7 nights back. Leakage is tested in
[`tests/test_forecast_demand.py`](../tests/test_forecast_demand.py).

| Model | MAE (orders/night) | WAPE | MAE on rainy, event and bank-holiday nights |
|---|---|---|---|
| **LightGBM** (Poisson) | **3.52** | **21.6%** | **3.13** |
| Same night, 4-week mean | 3.58 | 21.6% | 3.41 |
| Same night last week | 4.57 | 27.9% | 4.18 |

At about 16 orders a night, Poisson noise alone causes an expected miss of about 3.26 orders, so on ordinary
nights the strong models are near the limit. LightGBM's 8% gain on unusual nights comes from the weather and
calendar features. Runs, parameters, metrics and feature importance are tracked in MLflow.

## Engineering tests

| Suite | Count | Highlights |
|---|---|---|
| pytest | 81 | SQL validator (writes, stacked statements, catalogs, `pg_*`, CTE writes), read-only role limits, API auth and roles, rate limit, lockout, fail-closed network check, PII redaction on and off target, seed-data consistency, forecaster leakage, search quality |
| dbt data tests | 16 | uniqueness and not-null keys, accepted values, relationships, nightly totals reconcile with orders, no contact details in reviews |
| CI drift check | 1 | regenerated synthetic data must match the committed copy byte for byte |

## Running the evaluations

```bash
python -m evals.evaluate_search                  # no model needed
python -m evals.evaluate_sql --provider local    # ~15 min on an M-series Mac
python -m evals.evaluate_sql --rescore           # after editing a reference query
python -m evals.evaluate_chatbot                 # GRILLHOUSE_SEARCH=keyword for the baseline
```

Results are written to [`evals/results/`](../evals/results/).
