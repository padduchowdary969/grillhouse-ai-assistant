"""Download daily context for Manchester: weather history (Open-Meteo) and UK bank holidays (gov.uk).

Run from the project root:
    python -m pipelines.fetch_context [start] [end]      # dates as YYYY-MM-DD, default Apr 2025 - Sep 2026

Both sources are free, public and need no key. The result is cached in seed_data/context/daily_context.csv,
so the seed-data generator stays reproducible offline.
"""

import json
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import certifi
import pandas as pd

OUT = Path("seed_data/context/daily_context.csv")
MANCHESTER = {"latitude": 53.4808, "longitude": -2.2426}
WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
HOLIDAYS_URL = "https://www.gov.uk/bank-holidays.json"


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "grillhouse-ai-assistant"})
    # certifi's certificate bundle: python.org builds of Python on macOS don't use the system one
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=60, context=context) as response:
        return json.load(response)


def weather(start: str, end: str) -> pd.DataFrame:
    params = {**MANCHESTER, "start_date": start, "end_date": end, "timezone": "Europe/London",
              "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,wind_speed_10m_max"}
    daily = get_json(f"{WEATHER_URL}?{urllib.parse.urlencode(params)}")["daily"]
    df = pd.DataFrame(daily).rename(columns={
        "time": "date", "temperature_2m_max": "temp_max_c", "temperature_2m_min": "temp_min_c",
        "precipitation_sum": "precip_mm", "rain_sum": "rain_mm", "wind_speed_10m_max": "wind_max_kmh"})
    df["is_rainy"] = df["precip_mm"] >= 2.0
    return df


def bank_holidays() -> pd.DataFrame:
    events = get_json(HOLIDAYS_URL)["england-and-wales"]["events"]
    return pd.DataFrame({"date": [e["date"] for e in events], "bank_holiday": [e["title"] for e in events]})


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "2025-04-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-09-30"
    df = weather(start, end).merge(bank_holidays(), on="date", how="left")
    df["is_bank_holiday"] = df["bank_holiday"].notna()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(df)} days, {int(df['is_rainy'].sum())} rainy, {int(df['is_bank_holiday'].sum())} bank holidays)")


if __name__ == "__main__":
    main()
