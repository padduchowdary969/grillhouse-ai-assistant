"""Shared helpers for the labs: use the synthetic demo data, check what's running, print readable sections."""

import json
import os
import sys
import textwrap
import urllib.error
import urllib.request

# Labs run on the public synthetic dataset unless you say otherwise (GRILLHOUSE_DATA=data for the shop's own)
os.environ.setdefault("GRILLHOUSE_DATA", "seed_data")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("GRILLHOUSE_MODEL", "qwen3:8b")


def title(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def step(text: str) -> None:
    print(f"\n--- {text} " + "-" * max(0, 72 - len(text)))


def show(text: str, width: int = 140, limit: int | None = None) -> None:
    """Print text wrapped and indented; cut long text at `limit` characters."""
    if limit and len(text) > limit:
        text = text[:limit] + f"\n... ({len(text) - limit:,} more characters)"
    for line in text.splitlines() or [""]:
        print(textwrap.indent(textwrap.fill(line, width) if len(line) > width else line, "    "))


def need_ollama() -> None:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
            models = [m["name"] for m in json.load(r)["models"]]
    except (urllib.error.URLError, OSError):
        sys.exit("This lab needs Ollama. Open the Ollama app, then run the lab again.")
    for name in (MODEL, "nomic-embed-text:latest"):
        if name not in models:
            sys.exit(f"This lab needs the {name} model: ollama pull {name.removesuffix(':latest')}")


def need_database() -> None:
    import psycopg

    from app.config import db_url
    try:
        psycopg.connect(db_url(readonly=True), connect_timeout=3).close()
    except psycopg.OperationalError:
        sys.exit("This lab needs the demo database: docker compose up -d   (then run the lab again)")


def need_demo_reports() -> None:
    from pathlib import Path
    if not Path("seed_data/reports/ubereats_summary.md").exists():
        sys.exit("This lab needs the demo reports: python -m pipelines.run_all --no-db")


def chat(system: str, user: str, max_tokens: int = 300) -> dict:
    """One call to the local model. Returns the reply plus how many tokens went in and out."""
    body = {"model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0, "num_ctx": 16384, "num_predict": max_tokens}}
    request = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as r:
        data = json.load(r)
    return {"text": data["message"]["content"].strip(), "tokens_in": data.get("prompt_eval_count", 0),
            "tokens_out": data.get("eval_count", 0), "seconds": round(data.get("total_duration", 0) / 1e9, 1)}
