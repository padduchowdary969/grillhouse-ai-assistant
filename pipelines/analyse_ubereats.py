"""Turn the cleaned Uber Eats files into charts and a short written summary.

Run from the project root, after pipelines/clean_ubereats.py:
    python -m pipelines.analyse_ubereats

Everything is written to data/reports/, which stays private (data/ is git-ignored).
With GRILLHOUSE_DATA=seed_data it reads and writes seed_data/ instead.
"""

import os
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

DATA = Path(os.environ.get("GRILLHOUSE_DATA", "data"))  # set GRILLHOUSE_DATA=seed_data to use the sample files
CLEAN = DATA / "clean"
OUT = DATA / "reports"

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFT_HOURS = list(range(18, 24)) + list(range(0, 11))  # 18:00 through the 10:00 weekend close

# Chart colours: one blue for single-series charts, a light-to-dark blue ramp for magnitude
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE = "#2a78d6"
BLUE_RAMP = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
FUNNEL_STEPS = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "sans-serif", "font.size": 10, "text.color": INK,
    "axes.labelcolor": INK_2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": AXIS, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 14,
})


def gbp(x: float) -> str:
    return f"£{x:,.0f}"


def finish(fig, ax, name: str, grid_axis: str = "y") -> Path:
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    path = OUT / name
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def chart_monthly(monthly: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(9, 4))
    x = pd.to_datetime(monthly["month"])
    ax.plot(x, monthly["sales"], color=BLUE, linewidth=2, marker="o", markersize=5)
    peak = monthly.loc[monthly["sales"].idxmax()]
    last = monthly.iloc[-1]
    for row, va in ((peak, "bottom"), (last, "bottom")):
        ax.annotate(f"{pd.to_datetime(row['month']):%b %y}\n{gbp(row['sales'])}", (pd.to_datetime(row["month"]), row["sales"]),
                    textcoords="offset points", xytext=(0, 8), ha="center", va=va, fontsize=9, color=INK_2)
    ax.set_title("Monthly Uber Eats sales")
    ax.yaxis.set_major_formatter(lambda v, _: gbp(v))
    ax.set_ylim(0, monthly["sales"].max() * 1.2)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %y"))
    return finish(fig, ax, "1_monthly_sales.png")


def chart_items(items: pd.DataFrame, top: int = 10) -> Path:
    head = items.head(top)
    rest = pd.DataFrame([{"item": f"Other {len(items) - top} items", "sales": items["sales"].iloc[top:].sum()}])
    data = pd.concat([head, rest])[::-1]
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = [MUTED] + [BLUE] * top
    ax.barh(data["item"], data["sales"], color=colors, height=0.68)
    total = items["sales"].sum()
    for y, v in enumerate(data["sales"]):
        ax.text(v + total * 0.004, y, f"{gbp(v)}  ({v / total:.0%})", va="center", fontsize=9, color=INK_2)
    ax.set_title(f"Top {top} items by sales (Oct 2025 – Sep 2026)")
    ax.xaxis.set_major_formatter(lambda v, _: gbp(v))
    ax.set_xlim(0, data["sales"].max() * 1.25)
    ax.tick_params(axis="y", colors=INK, length=0)
    return finish(fig, ax, "2_top_items.png", grid_axis="x")


def chart_heatmap(hourly: pd.DataFrame) -> Path:
    grid = (hourly.pivot_table(index="trading_night", columns="hour", values="orders", aggfunc="sum")
            .reindex(index=DAYS, columns=SHIFT_HOURS).fillna(0))
    fig, ax = plt.subplots(figsize=(11, 4.2))
    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    im = ax.imshow(grid.values, cmap=cmap, aspect="auto")
    vmax = grid.values.max()
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = int(grid.values[i, j])
            if v:
                ax.text(j, i, v, ha="center", va="center", fontsize=8, color="white" if v > vmax * 0.55 else INK)
    ax.set_xticks(range(len(SHIFT_HOURS)), [f"{h:02d}" for h in SHIFT_HOURS])
    ax.set_yticks(range(len(DAYS)), [f"{d} night" for d in DAYS])
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(SHIFT_HOURS)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(DAYS)), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    ax.set_title("Orders by trading night and hour (a year of orders)")
    ax.set_xlabel("Hour the order was placed")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01).outline.set_visible(False)
    fig.tight_layout()
    path = OUT / "3_orders_heatmap.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def chart_nights(hourly: pd.DataFrame) -> Path:
    nights = hourly.groupby("trading_night")["sales"].sum().reindex(DAYS)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar([f"{d}" for d in DAYS], nights.values, color=BLUE, width=0.62)
    for x, v in enumerate(nights.values):
        ax.text(x, v, gbp(v), ha="center", va="bottom", fontsize=9, color=INK_2)
    ax.set_title("Sales by trading night (a night runs 18:00 to close)")
    ax.yaxis.set_major_formatter(lambda v, _: gbp(v))
    ax.set_ylim(0, nights.max() * 1.15)
    ax.tick_params(axis="x", colors=INK, length=0)
    return finish(fig, ax, "4_sales_by_night.png")


def chart_funnel(funnel: pd.DataFrame) -> Path:
    # Raw counts span 6k to 545k, so chart the pass-through rate of each step instead
    now = funnel.set_index("period").loc["this_period"]
    prev = funnel.set_index("period").loc["last_period"]
    steps = [("viewed_your_menu", "Saw store → opened menu"),
             ("added_item_to_order", "Opened menu → added item"),
             ("placed_an_order", "Added item → ordered")]
    labels = [label for _, label in steps][::-1]
    rates = [now[f"{s}_rate_pct"] for s, _ in steps][::-1]
    before = [prev[f"{s}_rate_pct"] for s, _ in steps][::-1]
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.barh(labels, rates, color=FUNNEL_STEPS[1:][::-1], height=0.6)
    for y, (r, b) in enumerate(zip(rates, before)):
        ax.text(r + 1, y, f"{r:.0f}%   (last year {b:.0f}%)", va="center", fontsize=9, color=INK_2)
    ax.set_xlim(0, 100)
    ax.set_title("How many customers make it to each next step")
    ax.tick_params(axis="y", colors=INK, length=0)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    return finish(fig, ax, "5_funnel.png", grid_axis="x")


# Keywords that group complaint comments (ratings of 3 or below) into themes
COMPLAINT_THEMES = {
    "Arrived cold": r"cold|not hot|room temperature|warm",
    "Small portion": r"portion|half of the box|not even filled|smaller",
    "Food quality": r"fake|not real|overcooked|not fresh|dry|terrible|smelt|\bill\b",
    "Too spicy": r"spicy",
    "Missing or wrong item": r"only one came|not the item|no gherkin",
    "Slow delivery": r"hours|took|missed multiple turns",
}


def chart_ratings(reviews: pd.DataFrame) -> Path:
    counts = reviews["rating"].value_counts().reindex([5, 4, 3, 2, 1], fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.barh([f"{s} star" for s in counts.index][::-1], counts.values[::-1], color=BLUE, height=0.6)
    for y, v in enumerate(counts.values[::-1]):
        ax.text(v + 2, y, f"{v}  ({v / counts.sum():.0%})", va="center", fontsize=9, color=INK_2)
    ax.set_xlim(0, counts.max() * 1.2)
    ax.set_title(f"Customer ratings ({len(reviews)} ratings, Apr – Oct 2026)")
    ax.tick_params(axis="y", colors=INK, length=0)
    return finish(fig, ax, "6_ratings.png", grid_axis="x")


def reviews_section(reviews: pd.DataFrame) -> str:
    low = reviews[reviews["rating"] <= 2]
    complaints = reviews.loc[(reviews["rating"] <= 3) & (reviews["comment"] != ""), "comment"]
    themes = {t: int(complaints.str.contains(p, case=False).sum()) for t, p in COMPLAINT_THEMES.items()}
    tags = reviews.loc[reviews["tags"] != "", "tags"].str.split("; ").explode().value_counts()
    by_type = reviews.groupby("fulfilment")["rating"].mean()
    theme_lines = "\n".join(f"- {t}: {n}" for t, n in sorted(themes.items(), key=lambda kv: -kv[1]) if n)
    tag_lines = "\n".join(f"- {t}: {n}" for t, n in tags.head(8).items())
    return f"""
## Customer ratings
- {len(reviews)} ratings, {reviews['rated_on'].min()} to {reviews['rated_on'].max()}; average **{reviews['rating'].mean():.2f} / 5**
- {(reviews['rating'] == 5).mean():.0%} gave 5 stars; {len(low)} ({len(low) / len(reviews):.0%}) gave 1 or 2 stars
- Delivery {by_type.get('delivery', float('nan')):.2f} vs pickup {by_type.get('pickup', float('nan')):.2f} average rating
- Median time from order to delivery: {reviews['delivery_minutes'].median():.0f} min overall, {low['delivery_minutes'].median():.0f} min for 1–2 star orders
- {(reviews['comment'] != '').sum()} ratings include a written comment

Complaint themes in comments rated 3 stars or below:
{theme_lines}

Most common rating tags:
{tag_lines}

![Ratings](6_ratings.png)
"""


def summary(monthly, items, hourly, funnel) -> str:
    year = monthly[monthly["month"] >= "2025-10"]
    peak = year.loc[year["sales"].idxmax()]
    low = year.loc[year["sales"].idxmin()]
    nights = hourly.groupby("trading_night")["sales"].sum().reindex(DAYS)
    by_hour = hourly.groupby("hour")["orders"].sum()
    outside = hourly[~hourly["within_opening_hours"]]
    weak = items[items["sales"] < 200]
    bottom = ", ".join(items.tail(3)["item"])
    extras = items[items["item"].str.contains(r"\b(?:coke|cola|fanta|pepsi|sprite|soda|water|shake|lassi|sauce|mayo)", case=False)]
    f = funnel.set_index("period").loc["this_period"]
    prev = funnel.set_index("period").loc["last_period"]
    top_n = int((items["cumulative_pct"] <= 80).sum()) + 1

    return f"""# Uber Eats performance: Oct 2025 – Sep 2026

Uber Eats orders only (no walk-in or other platforms).

## Headline numbers
- Sales: **{gbp(year['sales'].sum())}** from **{year['orders'].sum():,}** orders
- Average order: **£{year['sales'].sum() / year['orders'].sum():.2f}**
- Best month: {pd.to_datetime(peak['month']):%B %Y} ({gbp(peak['sales'])}); weakest: {pd.to_datetime(low['month']):%B %Y} ({gbp(low['sales'])})
- Last month vs first month of the year: {gbp(year['sales'].iloc[-1])} vs {gbp(year['sales'].iloc[0])} ({year['sales'].iloc[-1] / year['sales'].iloc[0] - 1:+.0%})
- Pickup is {year['sales_by_pickup'].sum() / year['sales'].sum():.1%} of sales

![Monthly sales](1_monthly_sales.png)

## Menu
- {len(items)} items sold; the top {top_n} make 80% of sales
- Best seller: {items.iloc[0]['item']} ({gbp(items.iloc[0]['sales'])}, {items.iloc[0]['pct_of_sales']:.0f}% of sales)
- {len(weak)} items sold under £200 all year; weakest sellers: {bottom}
- Drinks, shakes and sauces: {gbp(extras['sales'].sum())} ({extras['sales'].sum() / items['sales'].sum():.1%} of sales), about {extras['items_sold'].sum() / year['orders'].sum():.2f} per order

![Top items](2_top_items.png)

## When people order
- Busiest night: **{nights.idxmax()}** ({gbp(nights.max())}); quietest: **{nights.idxmin()}** ({gbp(nights.min())})
- Busiest hour: **{by_hour.idxmax():02d}:00** ({by_hour.max():,} orders over the year)
- Orders outside opening hours: {outside['orders'].sum():,} ({gbp(outside['sales'].sum())})

![Orders heatmap](3_orders_heatmap.png)

![Sales by night](4_sales_by_night.png)

## Funnel
- {f['viewed_store']:,.0f} saw the store → {f['viewed_your_menu']:,.0f} opened the menu ({f['viewed_your_menu_rate_pct']:.0f}%) → {f['added_item_to_order']:,.0f} added an item ({f['added_item_to_order_rate_pct']:.0f}%) → {f['placed_an_order']:,.0f} ordered ({f['placed_an_order_rate_pct']:.0f}%)
- Overall: {f['overall_conversion_pct']:.2f}% of store views became orders (last year {prev['overall_conversion_pct']:.2f}%)
- Menu → basket improved from {prev['added_item_to_order_rate_pct']:.0f}% to {f['added_item_to_order_rate_pct']:.0f}%; basket → order slipped from {prev['placed_an_order_rate_pct']:.0f}% to {f['placed_an_order_rate_pct']:.0f}%

![Funnel](5_funnel.png)
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    monthly = pd.read_csv(CLEAN / "ubereats_monthly.csv")
    items = pd.read_csv(CLEAN / "ubereats_items.csv")
    hourly = pd.read_csv(CLEAN / "ubereats_hourly.csv")
    funnel = pd.read_csv(CLEAN / "ubereats_funnel.csv")
    reviews = pd.read_csv(CLEAN / "ubereats_reviews.csv", keep_default_na=False, na_values={"delivery_minutes": [""]})

    charts = (chart_monthly(monthly), chart_items(items), chart_heatmap(hourly), chart_nights(hourly),
              chart_funnel(funnel), chart_ratings(reviews))
    for path in charts:
        print(f"wrote {path}")
    report = OUT / "ubereats_summary.md"
    report.write_text(summary(monthly, items, hourly, funnel) + reviews_section(reviews), encoding="utf-8")
    print(f"wrote {report}")


if __name__ == "__main__":
    main()
