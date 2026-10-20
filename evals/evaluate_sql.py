"""Score Text-to-SQL by execution match against a golden set of hand-checked reference queries.

Run from the project root, with the database and the model available:
    python -m evals.evaluate_sql                    # default provider (local)
    python -m evals.evaluate_sql --provider bedrock
    python -m evals.evaluate_sql --rescore           # re-check saved SQL after fixing a reference (no model calls)

A case passes when every column of the reference result appears in the model's result with the same values
(column names, extra columns and small rounding differences don't matter). When the reference returns a single
row, the model's first row is compared, so "which night is busiest?" passes whether it returns one night or all
seven in order. Results go to evals/results/sql_<provider>.csv and are summarised on screen.
"""

import argparse
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

from app.sql_tool import run
from app.text_to_sql import ask

GOLDEN = Path("evals/sql_golden.jsonl")
RESULTS = Path("evals/results")


def normalise(value):
    if isinstance(value, (Decimal, float, int)) and not isinstance(value, bool):
        return round(float(value), 1)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()[:10]
    if isinstance(value, str):
        return value.strip().lower()
    return value


def close(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(0.051, 0.005 * abs(a))
    return a == b


def column(rows, i):
    return [normalise(r[i]) for r in rows]


def matches(reference: list[tuple], candidate: list[tuple]) -> bool:
    if not reference:
        return not candidate
    if not candidate:
        return False
    if len(reference) == 1:
        candidate = candidate[:1]
    if len(candidate) != len(reference):
        return False
    used = set()
    for i in range(len(reference[0])):
        want = sorted(column(reference, i), key=str)
        for j in range(len(candidate[0])):
            got = sorted(column(candidate, j), key=str)
            if j not in used and all(close(a, b) for a, b in zip(want, got)):
                used.add(j)
                break
        else:
            return False
    return True


def rescore(cases: list[dict], path: Path) -> None:
    saved = pd.read_csv(path).set_index("id")
    changed = 0
    for case in cases:
        reference = run(case["sql"])
        got = run(saved.at[case["id"], "sql"]) if isinstance(saved.at[case["id"], "sql"], str) else None
        ok = bool(got and got.error is None and matches(reference.rows, got.rows))
        changed += ok != bool(saved.at[case["id"], "passed"])
        saved.at[case["id"], "passed"] = ok
    saved.reset_index().to_csv(path, index=False)
    print(f"rescored {path}: {int(saved['passed'].sum())}/{len(saved)} correct ({changed} changed)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default=None)
    parser.add_argument("--rescore", action="store_true", help="re-run the saved SQL instead of asking the model")
    args = parser.parse_args()
    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    name = args.provider or "local"
    if args.rescore:
        return rescore(cases, RESULTS / f"sql_{name}.csv")
    rows = []
    for case in cases:
        reference = run(case["sql"])
        assert reference.error is None, f"reference query for {case['id']} fails: {reference.error}"
        answer = ask(case["question"], provider=args.provider)
        got = answer.result.rows if answer.result and answer.result.error is None else []
        ok = matches(reference.rows, got)
        rows.append({"id": case["id"], "passed": ok, "attempts": answer.attempts, "latency_s": answer.latency_s,
                     "input_tokens": answer.input_tokens, "output_tokens": answer.output_tokens,
                     "question": case["question"], "sql": answer.sql, "answer": answer.answer.replace("\n", " ")})
        print(f"{'PASS' if ok else 'FAIL'}  {answer.latency_s:5.1f}s  {answer.attempts}x  {case['id']}")

    results = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    results.to_csv(RESULTS / f"sql_{name}.csv", index=False)
    print(f"\nprovider {name}: {results['passed'].sum()}/{len(results)} correct "
          f"({100 * results['passed'].mean():.0f}%), median {results['latency_s'].median():.0f}s, "
          f"{results['attempts'].gt(1).sum()} needed retries\nwrote {RESULTS / f'sql_{name}.csv'}")


if __name__ == "__main__":
    main()
