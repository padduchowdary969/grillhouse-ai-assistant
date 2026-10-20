"""Quality gate: search must not get worse. Keyword-only scores are what CI can measure (no Ollama there)."""

import psycopg
import pytest

from app.config import db_url
from evals.evaluate_search import score, summarise

# Current scores, 20 Oct 2026: keyword hit@1 0.90, hit@3 1.00; hybrid hit@1 1.00
MIN_KEYWORD = {"hit@1": 0.85, "hit@3": 1.0}
MIN_HYBRID = {"hit@1": 0.95, "hit@3": 1.0}


@pytest.fixture(scope="module")
def embedded():
    try:
        with psycopg.connect(db_url(readonly=True), connect_timeout=3) as conn:
            return conn.execute("SELECT count(embedding) > 0 FROM analytics.documents").fetchone()[0]
    except psycopg.OperationalError:
        pytest.skip("database not running (docker compose up -d db)")


def test_keyword_search_quality(embedded):
    scores = summarise(score(dense=False))
    for metric, floor in MIN_KEYWORD.items():
        assert scores[metric] >= floor, f"keyword {metric} fell to {scores[metric]:.2f} (floor {floor})"


def test_hybrid_search_quality(embedded):
    if not embedded:
        pytest.skip("needs document embeddings (Ollama)")
    scores = summarise(score(dense=True))
    for metric, floor in MIN_HYBRID.items():
        assert scores[metric] >= floor, f"hybrid {metric} fell to {scores[metric]:.2f} (floor {floor})"
