"""Settings shared across the project, read from the environment and the git-ignored .env file."""

import os
from pathlib import Path


def load_env(path: Path = Path(".env")) -> None:
    """Copy KEY=value lines from .env into the environment, without overriding values already set."""
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

DB_HOST = os.environ.get("GRILLHOUSE_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("GRILLHOUSE_DB_PORT", "5433"))
DB_NAME = os.environ.get("GRILLHOUSE_DB_NAME", "grillhouse")


def db_url(readonly: bool = False) -> str:
    """Connection string for the loader (owner) or for the copilot's SQL tool (read-only)."""
    if readonly:
        user, password = "copilot_readonly", os.environ.get("GRILLHOUSE_READONLY_PASSWORD", "")
    else:
        user, password = "grillhouse", os.environ.get("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
