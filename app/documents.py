"""Menu and policy search with citations: pgvector (meaning) + BM25 (keywords), merged by reciprocal rank fusion.

Indexing happens in the pipeline (pipelines/load_db.py calls index()); search() runs as the read-only user
against analytics.documents, which dbt copies from raw.documents.

    from app.documents import search
    for hit in search("Which items are gluten-free?"):
        print(hit.citation, hit.content[:80])
"""

import re
import urllib.error
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import psycopg
from rank_bm25 import BM25Okapi

from app.chatbot import embed, words
from app.config import db_url

RRF_K = 60
CANDIDATES = 20  # how many to take from each ranking before fusing


@dataclass
class Chunk:
    source: str
    heading: str
    content: str

    @property
    def citation(self) -> str:
        return f"{self.source} › {self.heading}" if self.heading else self.source


@dataclass
class Hit(Chunk):
    score: float = 0.0


def chunk_file(path: Path) -> list[Chunk]:
    """Markdown: one chunk per `## ` section (the title line is kept with each). Text files: one chunk."""
    text = path.read_text(encoding="utf-8").strip()
    if path.suffix != ".md":
        return [Chunk(path.name, "", text)]
    title = text.splitlines()[0].lstrip("# ").strip() if text.startswith("# ") else ""
    chunks = []
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        heading, _, body = part.partition("\n")
        chunks.append(Chunk(path.name, heading.strip(), f"{title}: {heading.strip()}\n{body.strip()}"))
    return chunks or [Chunk(path.name, "", text)]


def index(folder: Path, cur: psycopg.Cursor) -> int:
    """Chunk every document in `folder`, embed it if the embedding model is available, and store it."""
    chunks = [c for path in sorted(folder.glob("*")) if path.suffix in (".md", ".txt") for c in chunk_file(path)]
    try:
        vectors = embed([f"search_document: {c.content}" for c in chunks])
    except (urllib.error.URLError, OSError, KeyError):
        vectors = [None] * len(chunks)  # BM25 still works; dense search switches on once embeddings exist
    cur.execute("TRUNCATE raw.documents")
    with cur.copy("COPY raw.documents (source, heading, content, embedding) FROM STDIN") as copy:
        for chunk, vector in zip(chunks, vectors):
            copy.write_row((chunk.source, chunk.heading, chunk.content, None if vector is None else str(vector)))
    return len(chunks)


def search(question: str, k: int = 4) -> list[Hit]:
    with psycopg.connect(db_url(readonly=True), connect_timeout=5) as conn:
        rows = conn.execute("SELECT id, source, heading, content, embedding IS NOT NULL FROM analytics.documents").fetchall()
        if not rows:
            return []
        chunks = {r[0]: Chunk(r[1], r[2] or "", r[3]) for r in rows}
        ids = list(chunks)

        # Keywords: BM25 over the same light tokenizer the chatbot uses
        bm25 = BM25Okapi([words(chunks[i].content) or ["_"] for i in ids])
        keyword_scores = bm25.get_scores(words(question))
        by_keyword = [ids[i] for i in sorted(range(len(ids)), key=lambda i: -keyword_scores[i])
                      if keyword_scores[i] > 0][:CANDIDATES]

        # Meaning: cosine distance in pgvector, when embeddings exist and the model is reachable
        by_meaning = []
        if any(r[4] for r in rows):
            try:
                query_vector = str(embed([f"search_query: {question}"])[0])
                by_meaning = [r[0] for r in conn.execute(
                    "SELECT id FROM analytics.documents WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> %s::vector LIMIT %s", (query_vector, CANDIDATES)).fetchall()]
            except (urllib.error.URLError, OSError, KeyError):
                pass

    fused = Counter()
    for ranking in (by_keyword, by_meaning):
        for rank, doc_id in enumerate(ranking):
            fused[doc_id] += 1 / (RRF_K + rank)
    return [Hit(**vars(chunks[doc_id]), score=round(score, 4)) for doc_id, score in fused.most_common(k)]
