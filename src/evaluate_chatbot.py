"""Score the chatbot against a fixed set of questions, so changes to retrieval or prompts can be measured.

Run from the project root, after the clean, analyse and forecast scripts and with Ollama running:
    python src/evaluate_chatbot.py

Each test case checks two things:
  - retrieval: did the right knowledge section come back for the question?
  - answer: does the reply contain the expected facts (all of `must`, one of each `any` group, none of `never`)?
Expected values are read from the cleaned data, so the same cases work on real data and on sample_data/.
Results are written to <data>/reports/eval_results.csv.
"""

import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import chatbot  # noqa: E402

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday",
             "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}


def money_variants(value: float) -> list[str]:
    """£13,065.67 can be written as 13,065.67 / 13065.67 / 13,066 / 13066 / 13.1k ..."""
    whole = round(value)
    return [f"{value:,.2f}", f"{value:.2f}", f"{whole:,}", f"{whole}", f"{value / 1000:.1f}k"]


def day_variants(day: str) -> list[str]:
    return [DAY_NAMES[day], day]


def build_cases() -> list[dict]:
    items = pd.read_csv(chatbot.CLEAN / "ubereats_items.csv")
    hourly = pd.read_csv(chatbot.CLEAN / "ubereats_hourly.csv")
    monthly = pd.read_csv(chatbot.CLEAN / "ubereats_monthly.csv")
    forecast = pd.read_csv(chatbot.REPORTS / "forecast_monthly.csv")
    nights = hourly.groupby("trading_night")["sales"].sum()
    top, third = items.iloc[0], items.iloc[2]
    peak_month = monthly.loc[monthly["sales"].idxmax()]
    next_month = forecast.iloc[0]

    return [
        {"question": "Which item sells the most?", "section": "Menu items",
         "any": [[top["item"]]]},
        {"question": f"How much did {third['item']} sell and what is its average price?", "section": "Menu items",
         "any": [money_variants(third["sales"]), [f"{third['avg_price']:.2f}"]]},
        {"question": "Which night of the week is busiest?", "section": "",
         "any": [day_variants(nights.idxmax())]},
        {"question": "Which night of the week is quietest?", "section": "",
         "any": [day_variants(nights.idxmin())]},
        {"question": "What was our best month for sales?", "section": "Monthly sales",
         "any": [[pd.Period(peak_month["month"], "M").strftime("%B"), peak_month["month"]]]},
        {"question": f"What is the sales forecast for {pd.Period(next_month['month'], 'M').strftime('%B')}?",
         "section": "Forecast", "any": [money_variants(next_month["forecast"])]},
        {"question": "What time do we close?", "section": "Opening hours", "must": ["08:00"], "any": [["10:00", "10am"]]},
        {"question": "What do customers complain about?", "section": "Customer", "any": [["cold"], ["portion"]]},
        {"question": "What is our average customer rating?", "section": "Customer ratings",
         "any": [[f"{pd.read_csv(chatbot.CLEAN / 'ubereats_reviews.csv')['rating'].mean():.2f}"]]},
        {"question": "How many staff do we employ?", "section": "",
         "any": [["don't have", "do not have", "not available", "no information"]]},
        {"question": "What is our phone number?", "section": "",
         "any": [["don't have", "do not have", "not available", "no information"]], "never": [r"\b0\d{3}"]},
    ]


def check_answer(reply: str, case: dict) -> tuple[bool, str]:
    text = reply.lower().replace("£", "")
    missing = [m for m in case.get("must", []) if m.lower() not in text]
    missing += [" / ".join(group[:2]) for group in case.get("any", []) if not any(g.lower() in text for g in group)]
    forbidden = [p for p in case.get("never", []) if re.search(p, text)]
    ok = not missing and not forbidden
    return ok, "" if ok else f"missing {missing}" + (f", forbidden {forbidden}" if forbidden else "")


def main() -> None:
    chatbot.check_ollama()
    retriever = chatbot.Retriever(chatbot.build_knowledge())
    rows = []
    for case in build_cases():
        titles = [title for title, _ in retriever.search(case["question"])]
        retrieved = not case["section"] or any(t.startswith(case["section"]) for t in titles)
        start = time.time()
        reply = chatbot.answer(case["question"], retriever, history=[], stream_to=None)
        seconds = time.time() - start
        correct, why = check_answer(reply, case)
        rows.append({"question": case["question"], "retrieval_ok": retrieved, "answer_ok": correct,
                     "seconds": round(seconds, 1), "problem": why, "reply": reply.replace("\n", " ")})
        print(f"{'PASS' if correct else 'FAIL'}  {'R' if retrieved else 'r'}  {seconds:5.1f}s  {case['question']}"
              + (f"\n      {why}\n      reply: {reply[:160]}" if not correct else ""))

    results = pd.DataFrame(rows)
    results.to_csv(chatbot.REPORTS / "eval_results.csv", index=False)
    print(f"\nAnswers correct: {results['answer_ok'].sum()}/{len(results)}"
          f"   Retrieval hit: {results['retrieval_ok'].sum()}/{len(results)}"
          f"   Median time: {results['seconds'].median():.0f}s"
          f"\nwrote {chatbot.REPORTS / 'eval_results.csv'}")


if __name__ == "__main__":
    main()
