"""Build the whole demo dataset in one command: seed data -> clean -> reports -> database -> dbt models.

Run from the project root, with the database up (`docker compose up -d db`):
    python -m pipelines.run_all             # everything
    python -m pipelines.run_all --no-db     # files and reports only

Uses the cached weather in seed_data/context/; run `python -m pipelines.fetch_context` to refresh it.
"""

import os
import subprocess
import sys
import time

STEPS = [
    ("Generate seed data", [sys.executable, "-m", "pipelines.make_seed_data"]),
    ("Clean exports", [sys.executable, "-m", "pipelines.clean_ubereats"]),
    ("Analysis report", [sys.executable, "-m", "pipelines.analyse_ubereats"]),
    ("Forecast", [sys.executable, "-m", "pipelines.forecast_ubereats"]),
    ("Load database", [sys.executable, "-m", "pipelines.load_db"]),
    ("dbt models + tests", [sys.executable, "-m", "dbt.cli.main", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"]),
]
DB_STEPS = {"Load database", "dbt models + tests"}


def main() -> None:
    from app import config  # noqa: F401  loads .env so dbt sees the database password

    env = {**os.environ, "GRILLHOUSE_DATA": "seed_data", "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    skip_db = "--no-db" in sys.argv
    for name, command in STEPS:
        if skip_db and name in DB_STEPS:
            continue
        start = time.time()
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        status = "ok" if result.returncode == 0 else "FAILED"
        print(f"{status:6s} {name} ({time.time() - start:.1f}s)")
        if result.returncode:
            sys.exit(result.stdout[-3000:] + result.stderr[-3000:])
    print("Demo data ready.")


if __name__ == "__main__":
    main()
