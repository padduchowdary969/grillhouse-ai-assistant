"""Answer a business question by writing SQL, running it safely, and explaining the result.

    from app.text_to_sql import ask
    result = ask("Top 5 burgers last month, and how did weekends compare?")
    print(result.answer)
    print(result.sql)

The model sees the live schema plus business notes, writes one query, and gets the database's error back
(up to MAX_ATTEMPTS) if the safety layer rejects it or Postgres can't run it. A second call turns the result
table into a short answer. Every query goes through app.sql_tool (validation + read-only role).
"""

import json
import time
from dataclasses import dataclass, field
from datetime import date

from app.llm import get_provider
from app.sql_tool import QueryResult, run, schema_description

MAX_ATTEMPTS = 3

BUSINESS_NOTES = """Business rules (Sample Grill Kitchen, a late-night takeaway in Manchester selling on Uber Eats):
- The shop trades 18:00 to 08:00 (sometimes 10:00 on Saturday and Sunday mornings). trading_night is the date the
  shift started, so an order at 04:00 on Sunday has trading_night = Saturday. Use trading_night for "night",
  "day" and "weekday" questions. night_of_week values: 'Mon','Tue','Wed','Thu','Fri','Sat','Sun'.
- "Weekend" means Friday and Saturday nights (night_of_week IN ('Fri','Sat')).
- Money (sales, total, line_total, price) is GBP paid by customers, before Uber's commission.
- Only orders with status = 'completed' count as sales; daily_sales and item_sales_monthly already exclude
  cancelled orders.
- orders.is_late means delivered more than 10 minutes after the promised time; delay_reason is one of
  'courier_shortage', 'weather', 'kitchen_backlog', 'courier_delay'.
- daily_sales has one row per trading night, including nights with no orders, plus weather (is_rainy,
  temp_max_c, precip_mm), is_bank_holiday, event (text, null if none) and courier_shortage.
- item_sales_monthly.month is the first day of the month. menu_items.category values include 'Burgers',
  'Loaded fries', 'Chicken', 'Wraps', 'Sides', 'Drinks', 'Desserts', 'Sauces'.
- menu_items.dietary_tags and allergens are comma-separated text: use ILIKE '%vegan%' etc.
- Data covers trading nights from 2025-04-01 to 2026-09-29."""

EXAMPLES = """Examples:
Q: Which night of the week is busiest?
SQL: SELECT night_of_week, round(avg(orders), 1) AS avg_orders, round(avg(sales), 2) AS avg_sales
     FROM daily_sales GROUP BY night_of_week ORDER BY avg_orders DESC
Q: How many deliveries were late because of the weather in March 2026?
SQL: SELECT count(*) AS late_deliveries FROM orders
     WHERE delay_reason = 'weather' AND trading_night >= '2026-03-01' AND trading_night < '2026-04-01'
Q: Do rainy nights get more orders?
SQL: SELECT is_rainy, count(*) AS nights, round(avg(orders), 1) AS avg_orders FROM daily_sales GROUP BY is_rainy"""

SQL_SCHEMA = {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}


@dataclass
class Answer:
    question: str
    answer: str
    sql: str
    result: QueryResult | None
    attempts: int
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    errors: list[str] = field(default_factory=list)


def sql_system_prompt() -> str:
    return f"""You write one PostgreSQL SELECT query that answers the owner's question. Today is {date.today():%A %d %B %Y}.

Tables (schema analytics; write table names without a schema):
{schema_description()}

{BUSINESS_NOTES}

{EXAMPLES}

Return JSON {{"sql": "..."}} with a single SELECT. Round money to 2 decimals. Give columns clear names."""


ANSWER_SYSTEM = """You explain a database result to the owner of a takeaway. Answer the question in one to three short
sentences using only the numbers in the result; lead with the answer. Use £ for money and say it is before Uber's
commission when quoting sales. If the result is empty, say no matching data was found. Do not mention SQL."""


def ask(question: str, provider: str | None = None) -> Answer:
    llm = get_provider(provider)
    start = time.time()
    system, tokens_in, tokens_out = sql_system_prompt(), 0, 0
    prompt, errors, result, sql = f"Question: {question}", [], None, ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = llm.complete(system, prompt, json_schema=SQL_SCHEMA)
        tokens_in, tokens_out = tokens_in + reply.input_tokens, tokens_out + reply.output_tokens
        try:
            sql = json.loads(reply.text)["sql"]
        except (json.JSONDecodeError, KeyError, TypeError):
            sql = reply.text
        result = run(sql)
        if result.error is None:
            break
        errors.append(result.error)
        # Show the model its own query and the error, then let it try again
        prompt = f"Question: {question}\n\nYour previous query:\n{sql}\n\nIt failed with: {result.error}\nWrite a corrected query."
    if result is None or result.error:
        return Answer(question, "Sorry, I couldn't get that from the data.", sql, result, attempt,
                      round(time.time() - start, 2), tokens_in, tokens_out, errors)

    reply = llm.complete(ANSWER_SYSTEM, f"Question: {question}\n\nResult:\n{result.as_markdown()}", max_tokens=300)
    return Answer(question, reply.text, result.sql, result, attempt, round(time.time() - start, 2),
                  tokens_in + reply.input_tokens, tokens_out + reply.output_tokens, errors)


if __name__ == "__main__":
    import sys

    answer = ask(" ".join(sys.argv[1:]) or "Which night of the week is busiest?")
    print(answer.answer, f"\n\n{answer.sql}\n\n({answer.attempts} attempt(s), {answer.latency_s}s)")
