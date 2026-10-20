"""Keyword retrieval works without Ollama, so it can run in CI."""

from app.chatbot import Retriever

SECTIONS = [
    ("Menu items: sales, quantity sold and average price per item", "Double Smash Burger, 9.99"),
    ("Customer review comments with star rating (complaints, praise, feedback)", "Food arrived cold"),
    ("Opening hours", "18:00 to 08:00"),
]


def test_keyword_search_finds_the_right_section():
    retriever = Retriever(SECTIONS, mode="keyword")
    titles = [t for t, _ in retriever.search("What do customers complain about?", k=1)]
    assert titles[0].startswith("Customer review comments")


def test_opening_hours_always_included():
    retriever = Retriever(SECTIONS, mode="keyword")
    assert "Opening hours" in [t for t, _ in retriever.search("best selling burger", k=1)]
