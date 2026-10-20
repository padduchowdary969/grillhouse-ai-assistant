"""Leakage checks for the forecaster's features (no LightGBM needed)."""

import numpy as np
import pandas as pd

from pipelines.forecast_demand import add_features


def nights(n=60):
    dates = pd.date_range("2026-01-01", periods=n)
    return pd.DataFrame({"trading_night": dates, "orders": np.arange(n, dtype=float), "is_rainy": 0.0,
                         "temp_max_c": 10.0, "precip_mm": 0.0, "is_bank_holiday": 0.0, "has_event": 0.0})


def test_history_features_look_back_at_least_a_week():
    df = add_features(nights())
    row = df.iloc[40]  # orders == index, so lags are easy to read
    assert row["lag_7"] == 33 and row["lag_14"] == 26
    assert row["same_night_mean_4w"] == np.mean([33, 26, 19, 12])
    assert row["week_mean_lag_7"] == np.mean(range(27, 34))  # nights 27..33, all at least 7 nights back


def test_changing_the_next_week_does_not_change_its_features():
    """A whole week can be forecast from the night before it starts."""
    base, changed = nights(), nights()
    changed.loc[53:, "orders"] = 999  # the "future" week
    cols = ["lag_7", "lag_14", "same_night_mean_4w", "week_mean_lag_7"]
    pd.testing.assert_frame_equal(add_features(base).iloc[53:60][cols], add_features(changed).iloc[53:60][cols])
