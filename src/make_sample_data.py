"""Generate synthetic Uber Eats exports in sample_data/, so the project runs without any real business data.

Run from the project root:
    python src/make_sample_data.py

Every number, menu item and review here is invented. The files copy the layout of real Uber Eats Manager
exports, including their quirks (byte-order mark, float noise, duplicate item spellings, stray spaces),
so the cleaning script has the same work to do as on real files.
"""

import uuid
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("sample_data")
SEED = 42
STORE = "Sample Grill Kitchen"

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LAUNCH_MONTH = "2025-04"

# Relative busyness of each hour across a late-night shift (18:00-08:00, some weekend mornings to 10:00)
HOUR_WEIGHT = {18: 0.1, 19: 0.5, 20: 0.6, 21: 0.8, 22: 0.8, 23: 0.9, 0: 1.1, 1: 1.1, 2: 1.1, 3: 1.4,
               4: 1.6, 5: 1.4, 6: 1.1, 7: 0.7, 8: 0.4, 9: 0.2, 16: 0.01, 17: 0.05}
NIGHT_WEIGHT = {"Mon": 0.85, "Tue": 0.85, "Wed": 0.95, "Thu": 0.9, "Fri": 1.15, "Sat": 1.3, "Sun": 1.05}

# Invented menu: name, price, popularity weight
MENU = [
    ("Double Smash Burger", 9.99, 30), ("Peri Peri Loaded Fries", 9.49, 26), ("Sticky BBQ Loaded Fries", 9.49, 20),
    ("Firecracker Chicken Burger", 8.99, 15), ("Loaded  Cheese Fries", 8.49, 12), ("Lemon Pepper Tenders", 7.49, 11),
    ("Classic Cheeseburger", 7.49, 8), ("Hot Honey Wings", 6.99, 7), ("Chicken Wrap", 8.49, 4),
    ("Spicy Tenders", 7.99, 3.5), ("Triple Stack Burger", 10.99, 3), ("Garlic Parmesan Wings", 7.49, 2.8),
    ("Fries", 2.99, 2.5), ("Halloumi Burger", 8.99, 2), ("Chicken Loaded Fries", 6.49, 1.5),
    ("Cola", 1.99, 1.0), ("Southern Fried Burger", 6.49, 1.0), ("Smoky BBQ Tenders", 6.49, 0.9),
    ("Veggie Wrap", 5.99, 0.8), ("Orange Soda", 1.99, 0.8), ("Sweet Potato Fries", 3.49, 0.8),
    ("Chocolate Shake", 5.49, 0.7), ("Mozzarella Sticks", 3.99, 0.7), ("Onion Rings", 3.49, 0.5),
    ("cola", 1.99, 0.3), ("Garlic Mayo", 0.99, 0.3), ("Chilli Sauce", 0.99, 0.2), ("Vanilla Shake", 5.49, 0.2),
    ("Veg Burger", 6.49, 0.2), ("Cheesy Nachos", 4.99, 0.1), ("Mango Lassi", 2.99, 0.05),
]

GOOD_TAGS = ["restaurant_reliable_service", "restaurant_great_selection", "restaurant_sustainable_packaging",
             "restaurant_convenient", "restaurant_consistent", "restaurant_store_accommodating"]
BAD_TAGS = ["restaurant_not_tasty", "restaurant_not_worth_price", "restaurant_too_slow",
            "restaurant_missed_request", "restaurant_poor_packaging"]
GOOD_COMMENTS = ["Really tasty, will order again", "Great burger and the fries were crispy", "Lovely food, arrived hot",
                 "Best late night food around", "Big portions and good value", "Wings were amazing",
                 "Fast delivery and well packed", "Loaded fries were great"]
BAD_COMMENTS = ["Food arrived cold", "Portion was smaller than expected", "Far too spicy for me",
                "Missing a drink from my order", "Chicken was dry", "Took over an hour to arrive",
                "Not worth the price", "Fries were soggy and cold"]


def months() -> pd.PeriodIndex:
    return pd.period_range("2024-10", "2026-09", freq="M")


def make_monthly(rng: np.random.Generator) -> pd.DataFrame:
    rows, level = [], 0.0
    for m in months():
        if m < pd.Period(LAUNCH_MONTH, "M"):
            sales = orders = pickup_sales = pickup_orders = 0
        else:
            # Ramp up for six months after launch, then wander around a plateau
            age = (m - pd.Period(LAUNCH_MONTH, "M")).n
            target = 12500 * min(1.0, (age + 1) / 7)
            level = target * rng.normal(1, 0.1) if age < 7 else level * 0.4 + target * 0.6 * rng.normal(1, 0.12)
            ticket = rng.normal(26.5, 1.2)
            orders = max(int(level / ticket), 10)
            pickup_orders = int(orders * rng.uniform(0.01, 0.03))
            pickup_sales = round(pickup_orders * rng.normal(18, 3), 2)
            sales = round(orders * ticket, 2)
        delivery_orders = orders - pickup_orders
        delivery_sales = round(sales - pickup_sales, 2)

        def ticket_of(s, o):
            return s / o if o else 0

        rows.append({
            "Period": "This period" if m >= pd.Period("2025-10", "M") else "Last period",
            "Start Date": f"{m.start_time:%Y-%m-%d} 00:00:00.000", "End Date": f"{(m + 1).start_time:%Y-%m-%d} 00:00:00.000",
            "Time Increment": "Month", "Sales by Pickup": pickup_sales, "Sales by Delivery": delivery_sales, "Sales": sales,
            "Orders by Pickup": pickup_orders, "Orders by Delivery": delivery_orders, "Orders": orders,
            "Ticket Size by Pickup": ticket_of(pickup_sales, pickup_orders), "Ticket Size by Delivery": ticket_of(delivery_sales, delivery_orders),
            "Ticket Size": ticket_of(sales, orders), "Currency Code": "GBP",
        })
    return pd.DataFrame(rows)


def make_hourly(rng: np.random.Generator, total_sales: float, total_orders: int) -> pd.DataFrame:
    cells = []
    for day in DAYS:
        for hour, w in HOUR_WEIGHT.items():
            # Hours before midday belong to the previous night's shift; weekend mornings run later
            night = DAYS[(DAYS.index(day) - 1) % 7] if hour < 12 else day
            if hour == 9 and day not in ("Sat", "Sun"):
                w *= 0.4
            cells.append((day, hour, w * NIGHT_WEIGHT[night]))
    weights = np.array([c[2] for c in cells])
    orders = rng.multinomial(total_orders, weights / weights.sum())
    sales = orders * rng.normal(26.5, 2.0, len(cells)).clip(15)
    sales = np.round(sales * total_sales / sales.sum(), 2)
    sales[np.argmax(orders)] += round(total_sales - sales.sum(), 2)  # make the totals match exactly
    df = pd.DataFrame({"Day": [c[0] for c in cells], "Hour": [c[1] for c in cells], "Sales": sales, "Orders": orders})
    df = df[df["Orders"] > 0].copy()
    df["% of Total Sales"] = (100 * df["Sales"] / df["Sales"].sum()).round(2)
    df["% of Total Orders"] = (100 * df["Orders"] / df["Orders"].sum()).round(2)
    df["Ticket Size"] = df["Sales"] / df["Orders"]
    df["Currency Code"] = "GBP"
    df["Day"] = pd.Categorical(df["Day"], DAYS)
    df = df.sort_values(["Day", "Hour"])
    return df[["Day", "Hour", "Sales", "% of Total Sales", "Orders", "% of Total Orders", "Ticket Size", "Currency Code"]]


def make_items(rng: np.random.Generator, total_sales: float) -> pd.DataFrame:
    weights = np.array([w for _, _, w in MENU]) * rng.uniform(0.85, 1.15, len(MENU))
    sales = weights / weights.sum() * total_sales * rng.uniform(0.995, 1.0)
    rows = []
    for (name, price, _), s in zip(MENU, sales):
        sold = max(int(round(s / price)), 1)
        new_item = rng.random() < 0.15
        rows.append({"Item": name, "Sales": sold * price + rng.normal(0, 1e-9),  # float noise like the real export
                     "Sales %Δ": "" if new_item else round(rng.uniform(-80, 900), 2), "Items Sold": sold,
                     "Items Sold %Δ": "" if new_item else round(rng.uniform(-80, 900), 2), "Currency Code": "GBP"})
    return pd.DataFrame(rows).sort_values("Sales", ascending=False)


def make_funnel(rng: np.random.Generator, orders_now: int, orders_before: int) -> pd.DataFrame:
    def steps(orders, menu_rate, add_rate, order_rate):
        placed = int(orders * rng.uniform(1.03, 1.08))
        added = int(placed / order_rate)
        menu = int(added / add_rate)
        return int(menu / menu_rate), menu, added, placed

    now = steps(orders_now, 0.11, 0.27, 0.44)
    before = steps(orders_before, 0.12, 0.17, 0.47)
    cols = ["Viewed store", "Viewed your menu", "Added item to order", "Placed an order"]
    return pd.DataFrame([
        {"Period": "This period", "Start Date": "2025-10-01", "End Date": "2026-09-30", **dict(zip(cols, now)), "Store Selected": STORE},
        {"Period": "Last period", "Start Date": "2024-10-01", "End Date": "2025-09-30", **dict(zip(cols, before)), "Store Selected": ""},
    ])


def make_reviews(rng: np.random.Generator, n: int = 160) -> pd.DataFrame:
    store_uuid = str(uuid.UUID(int=int(rng.integers(0, 2**63))))
    start = pd.Timestamp("2026-04-12")
    rows = []
    for _ in range(n):
        day = start + pd.Timedelta(days=int(rng.integers(0, 185)))
        hour = int(rng.choice(list(HOUR_WEIGHT), p=np.array(list(HOUR_WEIGHT.values())) / sum(HOUR_WEIGHT.values())))
        ordered = day + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(0, 60)))
        rating = int(rng.choice([5, 4, 3, 2, 1], p=[0.76, 0.08, 0.04, 0.03, 0.09]))
        minutes = rng.normal(34 if rating >= 4 else 44, 10)
        completed = ordered + pd.Timedelta(minutes=max(minutes, 8))
        rated = completed + pd.Timedelta(hours=float(rng.uniform(0.2, 40)))
        pool_tags, pool_comments = (GOOD_TAGS, GOOD_COMMENTS) if rating >= 4 else (BAD_TAGS, BAD_COMMENTS)
        tags = ", ".join(rng.choice(pool_tags, size=int(rng.integers(1, 4)), replace=False)) if rng.random() < 0.45 else ""
        comment = str(rng.choice(pool_comments)) if rng.random() < (0.15 if rating >= 4 else 0.6) else ""
        pickup = rng.random() < 0.08
        rows.append({
            "Store": STORE, "External Store ID": "", "Store UUID": store_uuid, "Country": "United Kingdom",
            "Country Code": "GBR", "City": "Sampletown", "Order ID": f"{int(rng.integers(0, 16**5)):05X}",
            "Order UUID": str(uuid.UUID(int=int(rng.integers(0, 2**63)))),
            "Date Ordered": f"{ordered:%Y-%m-%d}", "Time Customer Ordered": f"{ordered:%Y-%m-%d %H:%M:%S}.000",
            "Order Completion Time": f"{completed:%Y-%m-%d %H:%M:%S}.000", "Rating Date": f"{rated:%Y-%m-%d}",
            "Rating Time": f"{rated:%Y-%m-%d %H:%M:%S}.000", "Rating Type": "consumer_to_merchant",
            "Rating Value": rating, "Rating Tags": tags, "Comment": comment,
            "Fulfillment Type": "Pickup" if pickup else "Delivery",
            "Order Channel": str(rng.choice(["iOS", "Android", "Web"], p=[0.64, 0.35, 0.01])), "Eats Brand": "Uber Eats",
        })
    return pd.DataFrame(rows)


def main() -> None:
    rng = np.random.default_rng(SEED)
    OUT.mkdir(exist_ok=True)
    monthly = make_monthly(rng)
    this_year = monthly[monthly["Period"] == "This period"]
    last_year = monthly[monthly["Period"] == "Last period"]
    files = {
        "ubereats_monthly_2026.csv": monthly,
        "ubereats_sales_by_hour_2026.csv": make_hourly(rng, round(this_year["Sales"].sum(), 2), int(this_year["Orders"].sum())),
        "ubereats_items_2026.csv": make_items(rng, this_year["Sales"].sum()),
        "ubereats_funnel_2026.csv": make_funnel(rng, int(this_year["Orders"].sum()), int(last_year["Orders"].sum())),
        "ubereats_reviews_2026.csv": make_reviews(rng),
    }
    for name, df in files.items():
        # The real exports start with a byte-order mark; the reviews export does not
        encoding = "utf-8" if "reviews" in name else "utf-8-sig"
        df.to_csv(OUT / name, index=False, encoding=encoding)
        print(f"wrote {OUT / name} ({len(df)} rows)")


if __name__ == "__main__":
    main()
