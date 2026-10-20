"""Load the seed dataset into PostgreSQL (schema `raw`), redacting personal details on the way in.

Run from the project root, with the database up (`docker compose up -d db`):
    python -m pipelines.load_db

Rebuilds every raw table from seed_data/ (orders, items, deliveries, menu, weather and events, reviews), then
checks row counts and that order totals match their line items.
"""

from pathlib import Path

import pandas as pd
import psycopg

from app.config import db_url
from app.documents import index
from pipelines.redact import redact

SEED = Path("seed_data")
SCHEMA = Path("db/schema.sql")

# table -> (csv file, columns in table order)
TABLES = {
    "menu_items": (SEED / "orders/menu_items.csv", ["item", "category", "price", "allergens", "dietary_tags", "spice_level"]),
    "orders": (SEED / "orders/orders.csv", ["order_id", "placed_at", "trading_night", "channel", "items", "total", "status"]),
    "order_items": (SEED / "orders/order_items.csv", ["order_id", "item", "quantity", "unit_price"]),
    "deliveries": (SEED / "orders/deliveries.csv", ["order_id", "promised_minutes", "actual_minutes", "status", "delay_reason"]),
    "daily_context": (SEED / "context/daily_context.csv", ["date", "temp_max_c", "temp_min_c", "precip_mm", "rain_mm",
                                                           "wind_max_kmh", "is_rainy", "bank_holiday", "is_bank_holiday"]),
    "events": (SEED / "orders/events.csv", ["trading_night", "event", "courier_shortage"]),
    "reviews": (SEED / "clean/ubereats_reviews.csv", ["order_id", "ordered_at", "hour", "trading_night", "delivery_minutes",
                                                      "rated_on", "rating", "tags", "comment", "fulfilment", "app"]),
}


def frame(table: str) -> pd.DataFrame:
    path, columns = TABLES[table]
    if not path.exists():
        raise SystemExit(f"{path} not found. Run make_seed_data and clean_ubereats with GRILLHOUSE_DATA=seed_data first.")
    df = pd.read_csv(path, keep_default_na=False, dtype=str)[columns]
    if table == "reviews":
        df["comment"] = df["comment"].map(redact)  # personal details never reach the database
    return df


def copy(cur: psycopg.Cursor, table: str, df: pd.DataFrame) -> None:
    columns = ", ".join(df.columns)
    with cur.copy(f"COPY raw.{table} ({columns}) FROM STDIN WITH (FORMAT csv, NULL '')") as copy_in:
        copy_in.write(df.to_csv(index=False, header=False))


def main() -> None:
    with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA.read_text())
        for table in TABLES:
            df = frame(table)
            copy(cur, table, df)
            print(f"loaded raw.{table} ({len(df)} rows)")
        print(f"indexed raw.documents ({index(SEED / 'knowledge', cur)} chunks)")
        # Every order's total must equal the sum of its lines
        cur.execute("""
            SELECT count(*) FROM raw.orders o
            JOIN (SELECT order_id, sum(quantity * unit_price) AS lines FROM raw.order_items GROUP BY order_id) i USING (order_id)
            WHERE abs(o.total - i.lines) > 0.01""")
        mismatched = cur.fetchone()[0]
        if mismatched:
            raise SystemExit(f"{mismatched} orders don't match their line items")
        cur.execute("SELECT count(*) FROM raw.reviews WHERE comment ~ '07\\d{3}\\s?\\d{3}\\s?\\d{3}|@'")
        if cur.fetchone()[0]:
            raise SystemExit("unredacted contact details found in raw.reviews")
    print("checks passed: order totals match line items, no contact details in reviews")


if __name__ == "__main__":
    main()
