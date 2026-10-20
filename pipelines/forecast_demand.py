"""Forecast orders for the next 7 trading nights with LightGBM, backtested against simple baselines and tracked
in MLflow, then turn the forecast into a buns-and-patties order.

Run from the project root, with the database loaded (pipelines.run_all):
    python -m pipelines.forecast_demand

On macOS LightGBM needs OpenMP (`brew install libomp`); the Docker image already has it.

Every history feature looks back at least 7 nights, so a whole week can be forecast from what is known on the
day before it starts. Calendar context (bank holidays, booked events) is known ahead; weather is taken as known
in the backtest (as a forecast would be) and left missing when it isn't, which LightGBM handles natively.
"""

import json
import os
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import psycopg

from app.config import db_url

OUT = Path("seed_data/reports")
HORIZON = 7
BACKTEST_WEEKS = 8
TRAIN_FROM = "2025-05-01"  # skip the launch month, when orders were near zero
FEATURES = ["night_of_week", "month", "months_since_launch", "is_rainy", "temp_max_c", "precip_mm",
            "is_bank_holiday", "has_event", "lag_7", "lag_14", "same_night_mean_4w", "week_mean_lag_7"]
PARAMS = {"objective": "poisson", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 10,
          "feature_fraction": 0.9, "verbose": -1, "seed": 42}
ROUNDS = 300
# Ingredients per burger sold: (buns, beef patties)
BURGERS = {"Double Smash Burger": (1, 2), "Triple Stack Burger": (1, 3), "Classic Cheeseburger": (1, 1),
           "Firecracker Chicken Burger": (1, 0), "Southern Fried Burger": (1, 0), "Halloumi Burger": (1, 0),
           "Veg Burger": (1, 0)}


def load_nights() -> pd.DataFrame:
    with psycopg.connect(db_url(readonly=True)) as conn:
        cur = conn.execute("""SELECT trading_night, orders, is_rainy, temp_max_c, precip_mm, is_bank_holiday,
                                     event IS NOT NULL AS has_event FROM analytics.daily_sales ORDER BY trading_night""")
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    df["trading_night"] = pd.to_datetime(df["trading_night"])
    for col in ("orders", "temp_max_c", "precip_mm"):
        df[col] = df[col].astype(float)
    for col in ("is_rainy", "is_bank_holiday", "has_event"):
        df[col] = df[col].astype(float)  # NaN stays NaN for unknown weather
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("trading_night").copy()
    df["night_of_week"] = df["trading_night"].dt.dayofweek
    df["month"] = df["trading_night"].dt.month
    launch = df["trading_night"].min()
    df["months_since_launch"] = (df["trading_night"] - launch).dt.days / 30.4
    y = df["orders"]
    df["lag_7"], df["lag_14"] = y.shift(7), y.shift(14)
    df["same_night_mean_4w"] = pd.concat([y.shift(7 * k) for k in range(1, 5)], axis=1).mean(axis=1)
    df["week_mean_lag_7"] = y.shift(7).rolling(7).mean()
    return df


def fit(train: pd.DataFrame):
    import lightgbm as lgb  # imported here so the rest of the module works without OpenMP

    data = lgb.Dataset(train[FEATURES], train["orders"], categorical_feature=["night_of_week"])
    return lgb.train(PARAMS, data, num_boost_round=ROUNDS)


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    error = np.abs(actual - predicted)
    return {"mae": float(error.mean()), "wape_pct": float(100 * error.sum() / actual.sum())}


def backtest(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling origin: for each of the last BACKTEST_WEEKS weeks, train on everything before it, predict it."""
    rows = []
    usable = df[df["trading_night"] >= TRAIN_FROM].dropna(subset=["lag_14", "same_night_mean_4w", "week_mean_lag_7"])
    end = usable["trading_night"].max()
    for week in range(BACKTEST_WEEKS, 0, -1):
        start = end - pd.Timedelta(days=HORIZON * week - 1)
        train = usable[usable["trading_night"] < start]
        test = usable[(usable["trading_night"] >= start) & (usable["trading_night"] < start + pd.Timedelta(days=HORIZON))]
        model = fit(train)
        for name, prediction in {
            "same_night_last_week": test["lag_7"].to_numpy(),
            "same_night_4_week_mean": test["same_night_mean_4w"].to_numpy(),
            "lightgbm": model.predict(test[FEATURES]),
        }.items():
            unusual = ((test["is_rainy"] == 1) | (test["has_event"] == 1) | (test["is_bank_holiday"] == 1)).to_numpy()
            rows.append({"week_start": start.date(), "model": name, **metrics(test["orders"].to_numpy(), prediction),
                         "unusual_nights": int(unusual.sum()),
                         "unusual_abs_error": float(np.abs(test["orders"].to_numpy() - prediction)[unusual].sum())})
    return pd.DataFrame(rows)


def next_week(df: pd.DataFrame, model) -> pd.DataFrame:
    """Forecast the 7 nights after the data ends. Weather unknown (NaN); calendar known."""
    last = df["trading_night"].max()
    future = pd.DataFrame({"trading_night": pd.date_range(last + pd.Timedelta(days=1), periods=HORIZON)})
    for col in ("orders", "is_rainy", "temp_max_c", "precip_mm"):
        future[col] = np.nan
    future["is_bank_holiday"], future["has_event"] = 0.0, 0.0
    combined = add_features(pd.concat([df[future.columns], future], ignore_index=True))
    horizon = combined.tail(HORIZON).copy()
    horizon["forecast_orders"] = model.predict(horizon[FEATURES]).round(1)
    return horizon[["trading_night", "forecast_orders"]]


def ingredients(forecast_orders: float) -> dict:
    """Buns and patties for the forecast, from burgers sold per order over the last 8 weeks."""
    with psycopg.connect(db_url(readonly=True)) as conn:
        recent = "o.status = 'completed' AND o.trading_night > (SELECT max(trading_night) - 56 FROM analytics.orders)"
        orders = conn.execute(f"SELECT count(*) FROM analytics.orders o WHERE {recent}").fetchone()[0]
        sold = dict(conn.execute(f"""SELECT i.item, sum(i.quantity) FROM analytics.orders o JOIN analytics.order_items i USING (order_id)
                                     WHERE {recent} GROUP BY i.item""").fetchall())
    burgers = {item: forecast_orders * sold.get(item, 0) / orders for item in BURGERS}
    return {"burgers": {item: round(n) for item, n in burgers.items() if n >= 0.5},
            "buns": round(sum(n * BURGERS[item][0] for item, n in burgers.items())),
            "patties": round(sum(n * BURGERS[item][1] for item, n in burgers.items()))}


def main() -> None:
    # Local SQLite tracking store; set MLFLOW_TRACKING_URI to use a shared server instead
    Path("mlruns").mkdir(exist_ok=True)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlruns/mlflow.db"))
    if mlflow.get_experiment_by_name("demand-forecast") is None:
        # Relative, so the same store works on the Mac and inside Docker (both run from the project root)
        mlflow.create_experiment("demand-forecast", artifact_location="mlruns/artifacts")
    mlflow.set_experiment("demand-forecast")
    df = add_features(load_nights())

    with mlflow.start_run(run_name="lightgbm-vs-baselines"):
        mlflow.log_params({**PARAMS, "rounds": ROUNDS, "horizon": HORIZON, "backtest_weeks": BACKTEST_WEEKS,
                           "features": ",".join(FEATURES)})
        scores = backtest(df)
        summary = scores.groupby("model")[["mae", "wape_pct"]].mean().sort_values("mae")
        totals = scores.groupby("model")[["unusual_abs_error", "unusual_nights"]].sum()
        summary["mae_unusual_nights"] = totals["unusual_abs_error"] / totals["unusual_nights"]
        # Chance alone: for Poisson counts with mean m, the expected absolute miss is about sqrt(2m/pi)
        noise_floor = float(np.sqrt(2 * df["orders"].tail(HORIZON * BACKTEST_WEEKS).mean() / np.pi))
        mlflow.log_metric("noise_floor_mae", noise_floor)
        for model, row in summary.iterrows():
            mlflow.log_metrics({f"{model}_mae": row["mae"], f"{model}_wape_pct": row["wape_pct"],
                                f"{model}_mae_unusual_nights": row["mae_unusual_nights"]})

        train = df[df["trading_night"] >= TRAIN_FROM].dropna(subset=["lag_14", "same_night_mean_4w", "week_mean_lag_7"])
        model = fit(train)
        forecast = next_week(df, model)
        plan = ingredients(forecast["forecast_orders"].sum())

        OUT.mkdir(parents=True, exist_ok=True)
        scores.to_csv(OUT / "demand_backtest.csv", index=False)
        forecast.to_csv(OUT / "demand_forecast.csv", index=False)
        (OUT / "demand_ingredients.json").write_text(json.dumps(plan, indent=2))
        model.save_model(str(OUT / "demand_model.txt"))
        importance = dict(zip(FEATURES, model.feature_importance("gain").round(0).tolist()))
        for path in ("demand_backtest.csv", "demand_forecast.csv", "demand_ingredients.json", "demand_model.txt"):
            mlflow.log_artifact(str(OUT / path))
        mlflow.log_dict(importance, "feature_importance.json")

    print("Backtest, mean over", BACKTEST_WEEKS, "weeks (orders per night):")
    print(summary.round(2).to_string())
    print(f"(noise floor: about {noise_floor:.2f} orders per night would be missed by chance alone)")
    print("\nNext 7 nights:")
    print(forecast.assign(trading_night=forecast["trading_night"].dt.strftime("%a %d %b")).to_string(index=False))
    print(f"\nTotal {forecast['forecast_orders'].sum():.0f} orders -> order {plan['buns']} buns and {plan['patties']} beef patties")


if __name__ == "__main__":
    main()
