"""The synthetic dataset must be internally consistent, or the demo's answers won't add up."""

from pathlib import Path

import pandas as pd
import pytest

SEED = Path("seed_data")


@pytest.fixture(scope="module")
def orders():
    return pd.read_csv(SEED / "orders/orders.csv", parse_dates=["placed_at"])


def test_order_totals_match_line_items(orders):
    items = pd.read_csv(SEED / "orders/order_items.csv")
    lines = (items["quantity"] * items["unit_price"]).groupby(items["order_id"]).sum()
    assert (orders.set_index("order_id")["total"] - lines).abs().max() < 0.01


def test_monthly_export_matches_orders(orders):
    export = pd.read_csv(SEED / "ubereats_monthly_2026.csv", encoding="utf-8-sig")
    sold = orders[orders["status"] == "completed"]
    by_month = sold.groupby(sold["placed_at"].dt.strftime("%Y-%m-01"))["total"].sum()
    for row in export[export["Orders"] > 0].itertuples():
        assert row.Sales == pytest.approx(by_month[row._2[:10]], abs=0.01)


def test_after_midnight_orders_belong_to_previous_night(orders):
    early = orders[orders["placed_at"].dt.hour < 12]
    gap = (early["placed_at"].dt.normalize() - pd.to_datetime(early["trading_night"])).dt.days
    assert (gap == 1).all()


def test_delay_reason_only_on_late_deliveries():
    d = pd.read_csv(SEED / "orders/deliveries.csv")
    delivered = d[d["status"] == "delivered"]
    late = delivered["actual_minutes"] - delivered["promised_minutes"] > 10
    assert delivered.loc[late, "delay_reason"].notna().all()
    assert delivered.loc[~late, "delay_reason"].isna().all()


def test_reviews_point_at_real_orders(orders):
    reviews = pd.read_csv(SEED / "ubereats_reviews_2026.csv")
    assert set(reviews["Order ID"]) <= set(orders["order_id"])


def test_rain_and_courier_shortages_shape_the_data(orders):
    """The 'why' features depend on these effects being visible."""
    ctx = pd.read_csv(SEED / "context/daily_context.csv")
    nights = (orders[orders["status"] == "completed"].groupby("trading_night").size().rename("n").reset_index()
              .merge(ctx, left_on="trading_night", right_on="date"))
    settled = nights[nights["trading_night"] >= "2025-10-01"]
    assert settled[settled["is_rainy"]]["n"].mean() > settled[~settled["is_rainy"]]["n"].mean()
