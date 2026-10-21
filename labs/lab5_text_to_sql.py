"""Lab 5: Text-to-SQL, step by step.

For numbers, the assistant doesn't paste data into the prompt. It asks the model to WRITE a query, checks it,
runs it on the database as a read-only user, and only then asks the model to explain the result.

    python -m labs.lab5_text_to_sql
    python -m labs.lab5_text_to_sql "How many late deliveries were there for each delay reason?"
"""

import json
import sys

from labs._common import need_database, need_ollama, show, step, title

need_ollama()
need_database()
from app import text_to_sql  # noqa: E402
from app.llm import get_provider  # noqa: E402
from app.sql_tool import SQLRejected, run, validate  # noqa: E402

question = " ".join(sys.argv[1:]) or "Do rainy nights get more orders than dry nights?"
title(f"Lab 5 · Text-to-SQL: {question!r}")
llm = get_provider("local")

step("1. What the model is told: the live schema, business rules and worked examples")
system = text_to_sql.sql_system_prompt()
schema = system[system.index("Tables"):system.index("Business rules")]
show(schema, limit=900)
print(f"    ... plus {len(text_to_sql.BUSINESS_NOTES.splitlines())} lines of business rules and 3 example queries "
      f"({len(system):,} characters in all)")

prompt = f"Question: {question}"
for attempt in range(1, text_to_sql.MAX_ATTEMPTS + 1):
    step(f"2.{attempt} The model writes a query (attempt {attempt})")
    reply = llm.complete(system, prompt, json_schema=text_to_sql.SQL_SCHEMA)
    sql = json.loads(reply.text)["sql"]
    show(sql)
    print(f"    ({reply.input_tokens:,} tokens in, {reply.output_tokens} out, {reply.latency_s}s)")

    step(f"3.{attempt} The safety check (sqlglot) and the database (read-only user)")
    result = run(sql)
    if result.error:
        print(f"    ✗ {result.error}")
        print("    → the error goes back to the model, which tries again")
        prompt = f"Question: {question}\n\nYour previous query:\n{sql}\n\nIt failed with: {result.error}\nWrite a corrected query."
        continue
    print(f"    ✓ passed; ran as:\n      {result.sql}")
    show(result.as_markdown(max_rows=10))
    break
else:
    sys.exit("\n    The model couldn't produce a working query in 3 attempts.")

step("4. The model explains the result in plain English")
explained = llm.complete(text_to_sql.ANSWER_SYSTEM, f"Question: {question}\n\nResult:\n{result.as_markdown()}", max_tokens=200)
show(explained.text)

step("5. The safety check against dangerous queries (no model involved)")
for bad in ["DROP TABLE orders", "SELECT * FROM raw.orders", "SELECT 1; DELETE FROM orders",
            "SELECT pg_sleep(60)", "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x"]:
    try:
        validate(bad)
        print(f"    ⚠ allowed: {bad}")
    except SQLRejected as err:
        print(f"    ✗ {bad:<62} → {err}")

print("""
What to notice
  • The model never sees the data, only table and column names. Your code runs the query and holds the numbers.
  • The numbers in the answer come from Postgres, not the model's memory, so they're exact.
  • Two independent locks: the validator refuses anything that isn't one read-only SELECT on approved tables,
    and the database user can't write, can't see raw tables and is stopped after 5 seconds.
  • When a query fails, the error message is the model's best teacher: it usually fixes it on the next try.

Try
  • python -m labs.lab5_text_to_sql "Which hour of the night has the most late deliveries?"
  • python -m labs.lab5_text_to_sql "What was the best month for sales?"   (the local model often gets this one wrong)
""")
