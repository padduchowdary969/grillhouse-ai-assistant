"""Forecast the next few months of Uber Eats sales and orders, and split them into a typical week.

Run from the project root, after src/clean_ubereats.py:
    python src/forecast_ubereats.py

With only monthly totals and one settled year (the store launched in April 2025), this uses simple
methods that are tested on past months; the most accurate one makes the forecast. Outputs go to
data/reports/, which stays private.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analyse_ubereats import BLUE, DAYS, GRID, INK, INK_2, MUTED, SHIFT_HOURS, finish, gbp

CLEAN = Path("data/clean")
OUT = Path("data/reports")

FIRST_SETTLED_MONTH = "2025-10"  # earlier months are the launch ramp-up
HORIZON = 3  # months ahead
BACKTEST_MONTHS = 6  # one-step-ahead tests on the last six known months
Z_80 = 1.28  # 80% range


# Each method takes the known history (oldest first) and returns forecasts for the next `h` months
def last_month(y: np.ndarray, h: int) -> np.ndarray:
    return np.repeat(y[-1], h)


def three_month_average(y: np.ndarray, h: int) -> np.ndarray:
    return np.repeat(y[-3:].mean(), h)


def linear_trend(y: np.ndarray, h: int) -> np.ndarray:
    slope, intercept = np.polyfit(np.arange(len(y)), y, 1)
    return intercept + slope * np.arange(len(y), len(y) + h)


METHODS = {"Last month": last_month, "3-month average": three_month_average, "Linear trend": linear_trend}


def backtest(y: np.ndarray) -> pd.DataFrame:
    """Pretend each of the last few months is unknown, forecast it from the months before, record the error."""
    rows = []
    for name, method in METHODS.items():
        errors = [method(y[:t], 1)[0] - y[t] for t in range(len(y) - BACKTEST_MONTHS, len(y))]
        errors = np.array(errors)
        rows.append({"method": name, "mae": np.abs(errors).mean(), "rmse": np.sqrt((errors ** 2).mean()),
                     "mape_pct": 100 * np.abs(errors / y[-BACKTEST_MONTHS:]).mean()})
    return pd.DataFrame(rows).sort_values("mae").reset_index(drop=True)


def forecast(series: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    y = series.to_numpy(dtype=float)
    scores = backtest(y)
    best = scores.iloc[0]
    point = METHODS[best["method"]](y, HORIZON)
    months = pd.period_range(pd.Period(series.index[-1], "M") + 1, periods=HORIZON, freq="M").astype(str)
    spread = Z_80 * best["rmse"] * np.sqrt(np.arange(1, HORIZON + 1))  # uncertainty grows with distance
    out = pd.DataFrame({"month": months, "forecast": point, "low": np.maximum(point - spread, 0), "high": point + spread})
    return out, scores


def typical_week(month: str, sales: float, orders: float, hourly: pd.DataFrame) -> pd.DataFrame:
    """Spread one month's forecast over a typical week using last year's night-by-hour pattern."""
    weeks = pd.Period(month, "M").days_in_month / 7
    grid = hourly.groupby(["trading_night", "hour"])[["sales", "orders"]].sum()
    share = grid / grid.sum()
    week = pd.DataFrame({"sales": share["sales"] * sales / weeks, "orders": share["orders"] * orders / weeks}).reset_index()
    week["month"] = month
    return week


def chart(monthly: pd.DataFrame, fc: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(9, 4))
    hist_x = pd.to_datetime(monthly["month"])
    fc_x = pd.to_datetime(fc["month"])
    ax.plot(hist_x, monthly["sales"], color=BLUE, linewidth=2, marker="o", markersize=5, label="Actual")
    joined_x = pd.concat([hist_x.iloc[-1:], fc_x])
    joined_y = np.concatenate([monthly["sales"].iloc[-1:], fc["forecast"]])
    ax.plot(joined_x, joined_y, color=BLUE, linewidth=2, linestyle="--", markevery=range(1, len(joined_x)),
            marker="o", markersize=5, markerfacecolor="white", label="Forecast")
    ax.fill_between(fc_x, fc["low"], fc["high"], color=BLUE, alpha=0.12, linewidth=0, label="80% range")
    # Label the first and last forecast months only, so the labels don't collide
    for x, v in [(fc_x.iloc[0], fc["forecast"].iloc[0]), (fc_x.iloc[-1], fc["forecast"].iloc[-1])][: 1 if HORIZON == 1 else 2]:
        ax.annotate(gbp(v), (x, v), textcoords="offset points", xytext=(0, 9), ha="center", fontsize=9, color=INK_2)
    ax.set_title("Monthly Uber Eats sales: actual and forecast")
    ax.yaxis.set_major_formatter(lambda v, _: gbp(v))
    ax.set_ylim(0, max(monthly["sales"].max(), fc["high"].max()) * 1.15)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %y"))
    ax.legend(frameon=False, loc="upper left", labelcolor=INK_2)
    return finish(fig, ax, "7_forecast.png")


def report(sales_fc, orders_fc, sales_scores, week: pd.DataFrame) -> str:
    best = sales_scores.iloc[0]
    first = week[week["month"] == sales_fc["month"].iloc[0]]
    nights = first.groupby("trading_night")[["sales", "orders"]].sum().reindex(DAYS)
    busiest = first.sort_values("orders", ascending=False).head(5)
    month_lines = "\n".join(
        f"| {pd.Period(s.month, 'M').strftime('%b %Y')} | {gbp(s.forecast)} | {gbp(s.low)} – {gbp(s.high)} | {o.forecast:,.0f} |"
        for s, o in zip(sales_fc.itertuples(), orders_fc.itertuples()))
    score_lines = "\n".join(f"| {r.method} | {gbp(r.mae)} | {r.mape_pct:.0f}% |" for r in sales_scores.itertuples())
    night_lines = "\n".join(f"| {d} | {gbp(r.sales)} | {r.orders:.0f} |" for d, r in nights.iterrows())
    peak_lines = "\n".join(f"- {r.trading_night} night, {r.hour:02d}:00 – about {r.orders:.1f} orders" for r in busiest.itertuples())
    return f"""
## Forecast

Method: **{best['method']}**, the most accurate of {len(sales_scores)} simple methods when tested on the last
{BACKTEST_MONTHS} months (typical miss {gbp(best['mae'])}, about {best['mape_pct']:.0f}%). Based on monthly totals only,
so it can't yet see seasonal patterns like a winter peak or school holidays.

| Month | Sales forecast | 80% range | Orders |
|---|---|---|---|
{month_lines}

How the methods scored (lower is better):

| Method | Average miss | Average miss % |
|---|---|---|
{score_lines}

### A typical week in {pd.Period(sales_fc['month'].iloc[0], 'M').strftime('%B %Y')}

| Night | Sales | Orders |
|---|---|---|
{night_lines}

Busiest hours of the week:
{peak_lines}

![Forecast](7_forecast.png)
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    monthly = pd.read_csv(CLEAN / "ubereats_monthly.csv")
    hourly = pd.read_csv(CLEAN / "ubereats_hourly.csv")
    settled = monthly[monthly["month"] >= FIRST_SETTLED_MONTH].set_index("month")

    sales_fc, sales_scores = forecast(settled["sales"])
    # Derive orders from sales with the recent average order value, so the two forecasts agree
    ticket = settled["sales"].iloc[-3:].sum() / settled["orders"].iloc[-3:].sum()
    orders_fc = sales_fc.assign(forecast=sales_fc["forecast"] / ticket)
    week = pd.concat([typical_week(m, s, o, hourly) for m, s, o in
                      zip(sales_fc["month"], sales_fc["forecast"], orders_fc["forecast"])])

    sales_fc.assign(orders=orders_fc["forecast"]).round(2).to_csv(OUT / "forecast_monthly.csv", index=False)
    week["shift_hour"] = (week["hour"] - 18) % 24
    week = week.sort_values(["month", "trading_night", "shift_hour"],
                            key=lambda s: s.map(DAYS.index) if s.name == "trading_night" else s)
    week.drop(columns="shift_hour").round(2).to_csv(OUT / "forecast_typical_week.csv", index=False)
    print(f"wrote {OUT / 'forecast_monthly.csv'}\nwrote {OUT / 'forecast_typical_week.csv'}")
    print(f"wrote {chart(monthly, sales_fc)}")
    (OUT / "forecast_summary.md").write_text(report(sales_fc, orders_fc, sales_scores, week), encoding="utf-8")
    print(f"wrote {OUT / 'forecast_summary.md'}")


if __name__ == "__main__":
    main()
