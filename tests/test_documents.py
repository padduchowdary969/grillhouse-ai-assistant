from pathlib import Path

import psycopg
import pytest

from app.config import db_url
from app.documents import chunk_file, search

KNOWLEDGE = Path("seed_data/knowledge")


def test_markdown_is_chunked_by_section():
    chunks = chunk_file(KNOWLEDGE / "policies.md")
    headings = [c.heading for c in chunks]
    assert "Allergens" in headings and "Halal" in headings
    allergens = next(c for c in chunks if c.heading == "Allergens")
    assert allergens.citation == "policies.md › Allergens"
    assert "Halal" not in allergens.content  # sections don't bleed into each other


def test_text_files_are_one_chunk():
    assert len(chunk_file(KNOWLEDGE / "opening_hours.txt")) == 1


@pytest.fixture(scope="module")
def embedded():
    """True when the documents have embeddings (Ollama was available at load time)."""
    try:
        with psycopg.connect(db_url(readonly=True), connect_timeout=3) as conn:
            return conn.execute("SELECT count(embedding) > 0 FROM analytics.documents").fetchone()[0]
    except psycopg.OperationalError:
        pytest.skip("database not running (docker compose up -d db)")


@pytest.mark.parametrize("question, citation, needs_meaning", [
    ("Is the chicken halal?", "policies.md › Halal", False),
    ("When do the buns get delivered?", "policies.md › Supplier terms", False),
    ("What happens if food arrives cold?", "policies.md › Refunds and complaints", False),
    # Keywords alone rank the Sides menu first ("fries"); only meaning search finds the allergen policy
    ("Can coeliacs eat the fries?", "policies.md › Allergens", True),
])
def test_search_cites_the_right_section(embedded, question, citation, needs_meaning):
    if needs_meaning and not embedded:
        pytest.skip("needs document embeddings (Ollama)")
    assert search(question, k=1)[0].citation == citation
