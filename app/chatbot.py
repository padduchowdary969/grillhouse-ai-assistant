"""Ask questions about the shop in plain English, answered by a free AI model running locally with Ollama.

Run from the project root, after the clean, analyse and forecast scripts:
    python -m app.chatbot                       # chat until you type "quit"
    python -m app.chatbot "Which night is busiest?"

Nothing leaves the computer: the knowledge comes from data/ (or GRILLHOUSE_DATA) and the model runs in Ollama.
For each question it retrieves the most relevant sections of that knowledge and asks the model to answer from them.
"""

import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("GRILLHOUSE_DATA", "data"))
CLEAN, REPORTS, KNOWLEDGE = DATA / "clean", DATA / "reports", DATA / "knowledge"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("GRILLHOUSE_MODEL", "qwen3:8b")
EMBED_MODEL = os.environ.get("GRILLHOUSE_EMBED_MODEL", "nomic-embed-text")
SEARCH = os.environ.get("GRILLHOUSE_SEARCH", "hybrid")  # "hybrid" (keywords + meaning) or "keyword"
TOP_K = 5  # sections sent with each question
ALWAYS_INCLUDE = {"Opening hours"}

SYSTEM_PROMPT = """You are the business assistant for a late-night takeaway that sells through Uber Eats.
You talk to the owner. Answer using only the facts provided with each question; if they don't contain the
answer, say "I don't have that information" rather than guessing. Use £ for money. All figures are Uber Eats
only (no walk-in or other apps). The shop trades 18:00 to 08:00, so an order at 04:00 on Sunday belongs to
Saturday night. When the facts include exceptions, mention them; when asked about opening or closing
times, always give both the usual time and the later weekend time. For tables,
read the numbers carefully and quote the highest or lowest values exactly. Monthly forecast figures cover a
whole month: never give one as the figure for a single night or day. Sales figures are what customers paid on
Uber Eats, before Uber's commission and fees, not the payout to the shop. Keep answers short and practical:
lead with the answer, then the key numbers."""

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
STOPWORDS = set("""a an and are at be by did do does for from how i in is it me my of on or our the this to
was we what when where which who why will with you your about much many show tell give""".split())


# ---------- knowledge ----------

def table(df: pd.DataFrame) -> str:
    return df.to_csv(index=False).strip()


def markdown_sections(path: Path) -> list[tuple[str, str]]:
    """Split a markdown report on its ## and ### headings, dropping image links."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", path.read_text(encoding="utf-8"))
    parts = re.split(r"^#{2,3} ", text, flags=re.M)
    return [(p.splitlines()[0].strip(), p.strip()) for p in parts[1:] if p.strip()]


def build_knowledge() -> list[tuple[str, str]]:
    sections = []
    for name in ("ubereats_summary.md", "forecast_summary.md"):
        if (REPORTS / name).exists():
            sections += markdown_sections(REPORTS / name)
    for path in sorted(KNOWLEDGE.glob("*.txt")):
        title = path.stem.replace("_", " ").capitalize()
        sections.append((title, path.read_text(encoding="utf-8").strip()))

    if (CLEAN / "ubereats_items.csv").exists():
        items = pd.read_csv(CLEAN / "ubereats_items.csv")
        sections.append(("Menu items: sales, quantity sold and average price per item (Oct 2025 - Sep 2026)",
                         table(items[["rank", "item", "sales", "items_sold", "avg_price", "pct_of_sales"]])))
    if (CLEAN / "ubereats_monthly.csv").exists():
        monthly = pd.read_csv(CLEAN / "ubereats_monthly.csv")
        # Written month names so "January" matches, for both keyword and meaning search
        monthly.insert(1, "month_name", pd.to_datetime(monthly["month"]).dt.strftime("%B %Y"))
        sections.append(("Monthly sales, orders and average order value by month (January to December)",
                         table(monthly[["month", "month_name", "sales", "orders", "ticket_size", "sales_by_pickup", "sales_by_delivery"]])))
    if (CLEAN / "ubereats_hourly.csv").exists():
        hourly = pd.read_csv(CLEAN / "ubereats_hourly.csv")
        grid = hourly.pivot_table(index="trading_night", columns="hour", values="orders", aggfunc="sum").reindex(DAYS)
        order = [h for h in list(range(18, 24)) + list(range(0, 18)) if h in grid.columns]
        sections.append(("Orders in a year by night of the week and hour (busy, quiet, peak times, staffing)",
                         "Total orders over the whole year (Oct 2025 - Sep 2026), not per night. Columns are the hour the order was placed.\n"
                         + grid[order].fillna(0).astype(int).rename_axis("night").reset_index().to_csv(index=False).strip()))
    if (CLEAN / "ubereats_reviews.csv").exists():
        reviews = pd.read_csv(CLEAN / "ubereats_reviews.csv", keep_default_na=False)
        written = reviews[reviews["comment"] != ""]
        sections.append(("Customer review comments with star rating (complaints, praise, feedback)",
                         table(written[["ordered_at", "rating", "delivery_minutes", "comment"]])))
    if (REPORTS / "forecast_typical_week.csv").exists():
        week = pd.read_csv(REPORTS / "forecast_typical_week.csv")
        first = week[week["month"] == week["month"].iloc[0]]
        grid = first.pivot_table(index="trading_night", columns="hour", values="orders", aggfunc="sum").reindex(DAYS)
        order = [h for h in list(range(18, 24)) + list(range(0, 18)) if h in grid.columns]
        sections.append((f"Forecast orders per hour for each night in a typical week of {first['month'].iloc[0]} (prep, staffing)",
                         "Expected orders in ONE night of a typical week (use this for prep and staffing). Columns are the hour.\n"
                         + grid[order].fillna(0).round(1).rename_axis("night").reset_index().to_csv(index=False).strip()))
    return sections


def next_nights_forecast(days: int = 7) -> str:
    """Forecast for the coming nights with real dates. Built per question, since the server runs for days."""
    path = REPORTS / "forecast_typical_week.csv"
    if not path.exists():
        return ""
    week = pd.read_csv(path)
    per_night = week.groupby(["month", "trading_night"])[["sales", "orders"]].sum()
    now = datetime.now()
    # Before midday we are still in the shift that started yesterday evening
    start = (now - timedelta(days=1) if now.hour < 12 else now).date()
    lines = ["Expected Uber Eats sales and orders for ONE night each (18:00 to closing). Use these for "
             "\"tonight\", \"tomorrow\" or a named night - never the monthly totals."]
    total_sales = total_orders = 0.0
    for offset in range(days):
        night = start + timedelta(days=offset)
        month = night.strftime("%Y-%m")
        month = month if month in per_night.index.get_level_values(0) else per_night.index.get_level_values(0)[0]
        row = per_night.loc[(month, night.strftime("%a"))]
        label = "Tonight" if offset == 0 else "Tomorrow night" if offset == 1 else f"{night:%A} night"
        lines.append(f"- {label}, {night:%A %d %B %Y}: about £{row['sales']:,.0f} from {row['orders']:.0f} orders")
        total_sales += row["sales"]
        total_orders += row["orders"]
    # Small models add up badly, so give the week's total ready-made
    lines.append(f"- Total for these {days} nights (this week): about £{total_sales:,.0f} from {total_orders:.0f} orders")
    return "\n".join(lines)


# ---------- retrieval ----------

def words(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9£]+", text.lower())
    # Very light stemming so "nights" matches "night" and "selling" matches "sell"
    return [re.sub(r"(ing|s)$", "", t) if len(t) > 4 else t for t in tokens if t not in STOPWORDS]


def embed(texts: list[str]) -> list[list[float]]:
    body = json.dumps({"model": EMBED_MODEL, "input": texts, "options": {"num_ctx": 8192}}).encode()
    request = urllib.request.Request(f"{OLLAMA_URL}/api/embed", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["embeddings"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


class Retriever:
    """Finds the knowledge sections most relevant to a question.

    Keyword search: TF-IDF over the words of each section (titles count double). Good at exact names.
    Hybrid search (default): also ranks sections by meaning with an embedding model, then merges the two
    rankings with reciprocal rank fusion, so "when do we get slammed?" still finds the busy-times section.
    """

    RRF_K = 60  # standard reciprocal-rank-fusion constant; dampens the weight of top ranks

    def __init__(self, sections: list[tuple[str, str]], mode: str = SEARCH):
        self.sections = sections
        self.docs = [Counter(words(title) * 2 + words(body)) for title, body in sections]
        df = Counter(w for doc in self.docs for w in doc)
        self.idf = {w: math.log(1 + len(self.docs) / n) for w, n in df.items()}
        self.vectors = None
        if mode == "hybrid":
            try:
                # nomic-embed-text expects these task prefixes; the title carries most meaning for tables
                self.vectors = embed([f"search_document: {title}\n{body[:2000]}" for title, body in sections])
            except (urllib.error.URLError, OSError, KeyError):
                print(f"(Embedding model {EMBED_MODEL} unavailable - using keyword search)", file=sys.stderr)
        self.mode = "hybrid" if self.vectors else "keyword"

    def keyword_scores(self, question: str) -> list[float]:
        terms = words(question)
        return [sum(self.idf.get(t, 0) * math.log(1 + doc[t]) for t in terms) for doc in self.docs]

    def search(self, question: str, k: int = TOP_K) -> list[tuple[str, str]]:
        keyword = self.keyword_scores(question)
        by_keyword = sorted(range(len(self.sections)), key=lambda i: -keyword[i])
        if self.vectors:
            query = embed([f"search_query: {question}"])[0]
            meaning = [cosine(query, v) for v in self.vectors]
            by_meaning = sorted(range(len(self.sections)), key=lambda i: -meaning[i])
            # Sections with no keyword overlap don't earn keyword-rank credit
            fused = Counter()
            for rank, i in enumerate(by_meaning):
                fused[i] += 1 / (self.RRF_K + rank)
            for rank, i in enumerate(i for i in by_keyword if keyword[i] > 0):
                fused[i] += 1 / (self.RRF_K + rank)
            picked = [i for i, _ in fused.most_common(k)]
        else:
            picked = [i for i in by_keyword[:k] if keyword[i] > 0] or by_keyword[:k]
        picked += [i for i, (title, _) in enumerate(self.sections) if title in ALWAYS_INCLUDE and i not in picked]
        return [self.sections[i] for i in picked]


# ---------- model ----------

def ask_model(messages: list[dict], stream_to=sys.stdout) -> str:
    body = json.dumps({"model": MODEL, "messages": messages, "stream": True, "think": False,
                       "options": {"temperature": 0.2, "num_ctx": 16384}}).encode()
    request = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body, headers={"Content-Type": "application/json"})
    reply = []
    with urllib.request.urlopen(request, timeout=300) as response:
        for line in response:
            chunk = json.loads(line)
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
            piece = chunk.get("message", {}).get("content", "")
            reply.append(piece)
            if stream_to:
                stream_to.write(piece)
                stream_to.flush()
    if stream_to:
        stream_to.write("\n")
    return "".join(reply).strip()


def build_messages(question: str, retriever: Retriever, history: list[dict]) -> list[dict]:
    """Everything the model is given for one question: rules, today's date, facts found by search, recent turns."""
    found = retriever.search(question)
    # Always-on facts (opening hours) go in the instructions, where a small model is less likely to skip them
    always = "\n\n".join(body for title, body in found if title in ALWAYS_INCLUDE)
    facts = "\n\n".join(f"### {title}\n{body}" for title, body in found if title not in ALWAYS_INCLUDE)
    nights = next_nights_forecast()
    if nights:
        facts = f"### Forecast for the next 7 nights (tonight, tomorrow, this week)\n{nights}\n\n{facts}"
    # The model doesn't know the date, so "next month" or "January" would otherwise be ambiguous
    system = (SYSTEM_PROMPT + f"\n\nToday is {date.today():%A %d %B %Y}. Months in the tables are written YYYY-MM"
              " (2026-01 means January 2026); \"next month\" means the first month in the forecast."
              + (f"\n\nShop details:\n{always}" if always else ""))
    return [{"role": "system", "content": system}, *history[-6:],
            {"role": "user", "content": f"Facts:\n{facts}\n\nQuestion: {question}"}]


def answer(question: str, retriever: Retriever, history: list[dict], stream_to=sys.stdout) -> str:
    reply = ask_model(build_messages(question, retriever, history), stream_to)
    # Keep the plain question (without the facts) in history so follow-ups stay short
    history += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
    return reply


def check_ollama() -> None:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as response:
            models = [m["name"] for m in json.load(response)["models"]]
    except (urllib.error.URLError, OSError):
        sys.exit("Ollama isn't running. Open the Ollama app, then try again.")
    if MODEL not in models:
        sys.exit(f"Model {MODEL} isn't downloaded. Run: ollama pull {MODEL}")


def main() -> None:
    check_ollama()
    sections = build_knowledge()
    if not sections:
        sys.exit(f"No knowledge found in {DATA}/. Run the clean, analyse and forecast scripts first.")
    retriever, history = Retriever(sections), []

    if len(sys.argv) > 1:
        answer(" ".join(sys.argv[1:]), retriever, history)
        return
    print(f"Grill House assistant ({MODEL}, {retriever.mode} search, {len(sections)} knowledge sections). Type 'quit' to stop.\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in {"quit", "exit", "q"}:
            break
        if question:
            print("Assistant: ", end="")
            answer(question, retriever, history)
            print()


if __name__ == "__main__":
    main()
