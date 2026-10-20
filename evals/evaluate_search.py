"""Score document search against a golden set of questions and the section that should come back.

Run from the project root, with the database loaded:
    python -m evals.evaluate_search

Reports hit@1, hit@3 and mean reciprocal rank (MRR) for keyword-only (BM25) and hybrid (BM25 + pgvector)
search. No model is needed to score, so this also runs in CI (keyword-only there, as CI has no Ollama).
"""

import json
from pathlib import Path

import pandas as pd

from app.documents import search

GOLDEN = Path("evals/search_golden.jsonl")
RESULTS = Path("evals/results")


def score(dense: bool) -> pd.DataFrame:
    rows = []
    for line in GOLDEN.read_text().splitlines():
        case = json.loads(line)
        citations = [h.citation for h in search(case["question"], k=5, dense=dense)]
        rank = next((i + 1 for i, c in enumerate(citations) if c in case["expected"]), None)
        rows.append({"question": case["question"], "expected": case["expected"][0], "rank": rank,
                     "top": citations[0] if citations else ""})
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame) -> dict:
    return {"hit@1": float((df["rank"] == 1).mean()), "hit@3": float((df["rank"] <= 3).mean()),
            "mrr": float((1 / df["rank"]).fillna(0).mean())}


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    table = {}
    for mode, dense in (("keyword", False), ("hybrid", True)):
        df = score(dense)
        df.to_csv(RESULTS / f"search_{mode}.csv", index=False)
        table[mode] = summarise(df)
        for r in df[df["rank"] != 1].itertuples():
            print(f"  {mode}: rank {r.rank or '-'} for {r.question!r} (top: {r.top})")
    print(pd.DataFrame(table).T.round(2).to_string())


if __name__ == "__main__":
    main()
