"""Score the chatbot against a fixed set of questions, so changes to retrieval or prompts can be measured.

Run from the project root, after the clean, analyse and forecast scripts and with Ollama running:
    python -m evals.evaluate_chatbot

Each test case checks two things:
  - retrieval: did the right knowledge section come back for the question?
  - answer: does the reply contain the expected facts (all of `must`, one of each `any` group, none of `never`)?
Expected values are read from the cleaned data, so the same cases work on real data and on seed_data/.
Results are written to <data>/reports/eval_results.csv.
"""

import re
import sys
import time
from pathlib import Path

import pandas as pd

from app import chatbot

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
    january = monthly.loc[monthly["month"] == "2026-01"].iloc[0]
    funnel = pd.read_csv(chatbot.CLEAN / "ubereats_funnel.csv").set_index("period").loc["this_period"]
    avg_rating = pd.read_csv(chatbot.CLEAN / "ubereats_reviews.csv")["rating"].mean()
    refusal = ["don't have", "do not have", "not available", "no information"]

    plain = [
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
         "any": [[f"{avg_rating:.2f}"]]},
        {"question": "How many staff do we employ?", "section": "", "any": [refusal]},
        {"question": "What is our phone number?", "section": "", "any": [refusal], "never": [r"\b0\d{3}"]},
    ]
    # Casual wording that shares few words with the data: the hard case for keyword search
    tricky = [
        {"question": "When do we get slammed?", "section": ("Orders in a year", "When people order", "Forecast orders"),
         "any": [day_variants(nights.idxmax())]},
        {"question": "What's our top dish?", "section": ("Menu",), "any": [[top["item"]]]},
        {"question": "What do people moan about?", "section": ("Customer",), "any": [["cold"], ["portion"]]},
        {"question": "How are folks rating us?", "section": ("Customer ratings",), "any": [[f"{avg_rating:.2f}", f"{avg_rating:.1f}"]]},
        {"question": "How much cash will we take next month?", "section": ("Forecast",),
         "any": [money_variants(next_month["forecast"])]},
        {"question": "Which grub barely sells?", "section": ("Menu",), "any": [list(items.tail(5)["item"])]},
        {"question": "Are people bailing before they order?", "section": ("Funnel",),
         "any": [[f"{funnel['viewed_your_menu_rate_pct']:.0f}%", f"{100 - funnel['viewed_your_menu_rate_pct']:.0f}%",
                  f"{funnel['placed_an_order_rate_pct']:.0f}%", f"{100 - funnel['placed_an_order_rate_pct']:.0f}%",
                  f"{funnel['overall_conversion_pct']:.2f}%"]]},
        {"question": "How did we do in January?", "section": ("Monthly sales",),
         "any": [money_variants(january["sales"])]},
        {"question": "Who's our accountant?", "section": "", "any": [refusal]},
    ]
    # Relative dates: answers must be one night (or the 7-night total), never a monthly figure
    nights_text = chatbot.next_nights_forecast()
    tonight = re.search(r"Tonight.*?£([\d,]+) from (\d+)", nights_text)
    week_total = re.search(r"Total.*?£([\d,]+)", nights_text)
    monthly_figures = [rf"{round(v):,}" for v in forecast["forecast"]]
    dated = [
        {"question": "What is the sales forecast for tonight?", "section": "",
         "any": [[tonight.group(1)]], "never": monthly_figures},
        {"question": "How many orders will we get tonight?", "section": "", "any": [[tonight.group(2)]], "never": monthly_figures},
        {"question": "How much will we take this week?", "section": "", "any": [[week_total.group(1)]], "never": monthly_figures},
    ] if tonight and week_total else []
    return ([{**c, "set": "plain"} for c in plain] + [{**c, "set": "tricky"} for c in tricky]
            + [{**c, "set": "dated"} for c in dated])


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
        wanted = (case["section"],) if isinstance(case["section"], str) else case["section"]
        retrieved = not case["section"] or any(t.startswith(w) for t in titles for w in wanted)
        start = time.time()
        reply = chatbot.answer(case["question"], retriever, history=[], stream_to=None)
        seconds = time.time() - start
        correct, why = check_answer(reply, case)
        rows.append({"set": case["set"], "question": case["question"], "retrieval_ok": retrieved, "answer_ok": correct,
                     "seconds": round(seconds, 1), "problem": why, "reply": reply.replace("\n", " ")})
        print(f"{'PASS' if correct else 'FAIL'}  {'R' if retrieved else 'r'}  {seconds:5.1f}s  {case['question']}"
              + (f"\n      {why}\n      reply: {reply[:160]}" if not correct else ""))

    results = pd.DataFrame(rows)
    results.to_csv(chatbot.REPORTS / "eval_results.csv", index=False)
    print(f"\nSearch: {retriever.mode}")
    for name, group in results.groupby("set", sort=False):
        print(f"{name:7s} answers {group['answer_ok'].sum()}/{len(group)}   retrieval {group['retrieval_ok'].sum()}/{len(group)}")
    print(f"total   answers {results['answer_ok'].sum()}/{len(results)}   retrieval {results['retrieval_ok'].sum()}/{len(results)}"
          f"   median {results['seconds'].median():.0f}s\nwrote {chatbot.REPORTS / 'eval_results.csv'}")


if __name__ == "__main__":
    main()
