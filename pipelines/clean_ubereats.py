"""Clean the raw Uber Eats Manager exports in data/ and write tidy copies to data/clean/.

Run from the project root:
    python -m pipelines.clean_ubereats
"""

import os
import os
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("GRILLHOUSE_DATA", "data"))  # set GRILLHOUSE_DATA=seed_data to use the sample files
OUT = DATA / "clean"

# The shop trades 18:00-08:00, so an order at 04:00 Sunday belongs to Saturday night.
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
OPEN_HOUR, CLOSE_HOUR = 18, 8
WEEKEND_CLOSE_HOUR = 10  # sometimes stays open until 10:00 on Saturday and Sunday mornings


def read(name: str) -> pd.DataFrame:
    # utf-8-sig strips the invisible byte-order mark Uber Eats puts at the start of each file
    df = pd.read_csv(DATA / name, encoding="utf-8-sig")
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace("%δ", "pct_change", regex=False)
        .str.replace("%", "pct", regex=False)
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
    )
    if "currency_code" in df:
        assert (df["currency_code"] == "GBP").all(), "expected all values in GBP"
        df = df.drop(columns="currency_code")
    return df


def clean_monthly() -> pd.DataFrame:
    df = read("ubereats_monthly_2026.csv")
    df["month"] = pd.to_datetime(df["start_date"]).dt.to_period("M").astype(str)
    df = df[df["orders"] > 0]  # months before the store joined Uber Eats are all zeros
    df = df.drop(columns=["start_date", "end_date", "time_increment", "period"])
    return df[["month"] + [c for c in df.columns if c != "month"]].round(2)


def clean_items() -> pd.DataFrame:
    df = read("ubereats_items_2026.csv")
    # Collapse spacing so "Loaded beef  fries" matches, and merge case variants like "Fanta orange"
    df["item"] = df["item"].str.split().str.join(" ")
    df["key"] = df["item"].str.lower()
    # Keep the spelling with the most sales as the display name
    names = df.sort_values("sales", ascending=False).drop_duplicates("key").set_index("key")["item"]
    # The %-change columns compare against a year when the store was barely trading, so drop them
    df = df.groupby("key", as_index=False)[["sales", "items_sold"]].sum()
    df["item"] = df["key"].map(names)
    df["avg_price"] = df["sales"] / df["items_sold"]
    df = df.sort_values("sales", ascending=False)
    df["pct_of_sales"] = 100 * df["sales"] / df["sales"].sum()
    df["cumulative_pct"] = df["pct_of_sales"].cumsum()
    df.insert(0, "rank", range(1, len(df) + 1))
    return df[["rank", "item", "sales", "items_sold", "avg_price", "pct_of_sales", "cumulative_pct"]].round(2)


def clean_hourly() -> pd.DataFrame:
    df = read("ubereats_sales_by_hour_2026.csv")
    df = df.rename(columns={"pct_of_total_sales": "pct_of_sales", "pct_of_total_orders": "pct_of_orders"})
    # Hours before midday belong to the shift that started the previous evening
    day_idx = df["day"].map(DAYS.index)
    df["trading_night"] = [DAYS[(d - 1) % 7] if h < 12 else DAYS[d] for d, h in zip(day_idx, df["hour"])]
    close = df["day"].isin(["Sat", "Sun"]).map({True: WEEKEND_CLOSE_HOUR, False: CLOSE_HOUR})
    df["within_opening_hours"] = (df["hour"] >= OPEN_HOUR) | (df["hour"] < close)
    # Sort hours in shift order: 18, 19 ... 23, 0, 1 ... 17
    df["shift_hour"] = (df["hour"] - OPEN_HOUR) % 24
    df = df.sort_values(["trading_night", "shift_hour"], key=lambda s: s.map(DAYS.index) if s.name == "trading_night" else s)
    return df.drop(columns="shift_hour").round(2)


def clean_funnel() -> pd.DataFrame:
    df = read("ubereats_funnel_2026.csv").drop(columns="store_selected")
    df["period"] = df["period"].str.lower().str.replace(" ", "_")
    steps = ["viewed_store", "viewed_your_menu", "added_item_to_order", "placed_an_order"]
    for prev, step in zip(steps, steps[1:]):
        df[f"{step}_rate_pct"] = 100 * df[step] / df[prev]
    df["overall_conversion_pct"] = 100 * df["placed_an_order"] / df["viewed_store"]
    return df.round(2)


def clean_reviews() -> pd.DataFrame:
    df = read("ubereats_reviews_2026.csv")
    assert (df["rating_type"] == "consumer_to_merchant").all(), "expected only customer ratings of the store"
    ordered = pd.to_datetime(df["time_customer_ordered"])
    out = pd.DataFrame({
        "order_id": df["order_id"],  # short code shown in Uber Eats Manager; internal UUIDs are dropped
        "ordered_at": ordered.dt.strftime("%Y-%m-%d %H:%M"),
        "hour": ordered.dt.hour,
        # Orders before midday belong to the shift that started the previous evening
        "trading_night": (ordered - pd.Timedelta(hours=12)).dt.strftime("%a"),
        "delivery_minutes": (pd.to_datetime(df["order_completion_time"]) - ordered).dt.total_seconds().div(60).round(),
        "rated_on": df["rating_date"],
        "rating": df["rating_value"].astype(int),
        # "restaurant_not_tasty, restaurant_too_slow" -> "not tasty; too slow"
        "tags": df["rating_tags"].fillna("").str.split(",").apply(
            lambda tags: "; ".join(t.strip().removeprefix("restaurant_").replace("_", " ") for t in tags if t.strip())),
        # Some comments contain a literal "\n" instead of a line break
        "comment": df["comment"].fillna("").str.replace(r"\\n|\s+", " ", regex=True).str.strip(),
        "fulfilment": df["fulfillment_type"].str.lower(),
        "app": df["order_channel"],
    })
    return out.sort_values("ordered_at").reset_index(drop=True)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    monthly, items, hourly, funnel = clean_monthly(), clean_items(), clean_hourly(), clean_funnel()
    reviews = clean_reviews()

    # The three sales reports should agree on the same 12 months (Oct 2025 - Sep 2026)
    this_year = monthly[monthly["month"] >= "2025-10"]
    assert abs(this_year["sales"].sum() - hourly["sales"].sum()) < 1, "monthly and hourly totals differ"
    assert this_year["orders"].sum() == hourly["orders"].sum(), "monthly and hourly order counts differ"
    assert abs(items["sales"].sum() / hourly["sales"].sum() - 1) < 0.01, "item sales off by more than 1%"

    for name, df in {"monthly": monthly, "items": items, "hourly": hourly, "funnel": funnel, "reviews": reviews}.items():
        path = OUT / f"ubereats_{name}.csv"
        df.to_csv(path, index=False)
        print(f"wrote {path} ({len(df)} rows)")


if __name__ == "__main__":
    main()
