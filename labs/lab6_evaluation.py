"""Lab 6: evaluation, or how you know a change helped.

Run the same small golden set twice: once with the full Text-to-SQL prompt, once with the business rules removed
("trading night", "weekend means Friday and Saturday", "only completed orders count"...). A case passes when the
model's query returns the same numbers as a hand-checked reference query.

    python -m labs.lab6_evaluation          # about 3 minutes on the local model
"""

import json
import time
from pathlib import Path

from labs._common import need_database, need_ollama, step, title

need_ollama()
need_database()
from app import text_to_sql  # noqa: E402
from app.sql_tool import run  # noqa: E402
from evals.evaluate_sql import matches  # noqa: E402

CASES = ["busiest_night", "weekend_share", "cancel_rate", "late_reasons", "rain_effect", "vegan_items",
         "avg_order_value_jan", "event_nights"]
golden = {c["id"]: c for c in map(json.loads, Path("evals/sql_golden.jsonl").read_text().splitlines())}
cases = [golden[c] for c in CASES]

title("Lab 6 · Does the business-rules block in the prompt earn its place?")


def score(label: str) -> list[bool]:
    step(label)
    results = []
    for case in cases:
        start = time.time()
        answer = text_to_sql.ask(case["question"], provider="local")
        got = answer.result.rows if answer.result and not answer.result.error else []
        ok = matches(run(case["sql"]).rows, got)
        results.append(ok)
        print(f"    {'PASS' if ok else 'FAIL'}  {time.time() - start:4.1f}s  {case['question']}")
    print(f"    → {sum(results)}/{len(results)} correct")
    return results


with_rules = score("A · full prompt (schema + business rules + examples)")
saved = text_to_sql.BUSINESS_NOTES
text_to_sql.BUSINESS_NOTES = "Business rules: (none given)"
try:
    without_rules = score("B · same prompt with the business rules removed")
finally:
    text_to_sql.BUSINESS_NOTES = saved

step("Comparison")
print(f"    with rules {sum(with_rules)}/{len(cases)}   ·   without rules {sum(without_rules)}/{len(cases)}")
for case, a, b in zip(cases, with_rules, without_rules):
    if a != b:
        print(f"    {'lost' if a else 'gained'} without rules: {case['question']}")

print("""
What to notice
  • A score turns "this prompt feels better" into a number you can compare. Change one thing at a time.
  • The cases that flip usually depend on a rule the model can't guess: weekends mean Fri and Sat nights here,
    only completed orders count, vegan is a tag in a comma-separated column.
  • 8 questions is a small sample: one flip is 12.5 points, and the local model isn't fully deterministic.
    That's why the real golden set has 50 cases (python -m evals.evaluate_sql).
  • Scoring by the query's RESULT, not its text, means any correct query passes, however it's written.

Try
  • Remove the examples instead: set text_to_sql.EXAMPLES = "" in the same way and compare.
  • Add a case of your own to evals/sql_golden.jsonl (a question plus a reference query) and include its id in CASES.
""")
