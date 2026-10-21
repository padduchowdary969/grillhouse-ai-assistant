"""Lab 3: retrieval, or how the assistant picks which facts to show the model.

The assistant's knowledge is cut into sections (reports, tables, opening hours). For each question it ranks the
sections three ways and keeps the top 5:
  keyword  TF-IDF: rare words that appear in both the question and the section score highest
  meaning  cosine similarity of embeddings (Lab 2)
  hybrid   reciprocal rank fusion: each ranking gives a section 1 / (60 + its rank), and the scores are added

    python -m labs.lab3_retrieval
    python -m labs.lab3_retrieval "which grub barely sells?"
"""

import sys
from collections import Counter

from labs._common import need_demo_reports, need_ollama, step, title

need_ollama()
need_demo_reports()
from app import chatbot  # noqa: E402

question = " ".join(sys.argv[1:]) or "What do people moan about?"
title(f"Lab 3 · Which facts get picked for {question!r}?")

sections = chatbot.build_knowledge()
retriever = chatbot.Retriever(sections, mode="hybrid")
titles = [t for t, _ in sections]

step(f"1. The knowledge base: {len(sections)} sections")
for t, body in sections:
    print(f"    {len(body):6,} chars  {t[:80]}")

keyword = retriever.keyword_scores(question)
by_keyword = sorted(range(len(sections)), key=lambda i: -keyword[i])
query = chatbot.embed([f"search_query: {question}"])[0]
meaning = [chatbot.cosine(query, v) for v in retriever.vectors]
by_meaning = sorted(range(len(sections)), key=lambda i: -meaning[i])
fused = Counter()
for rank, i in enumerate(by_meaning):
    fused[i] += 1 / (retriever.RRF_K + rank)
for rank, i in enumerate(i for i in by_keyword if keyword[i] > 0):
    fused[i] += 1 / (retriever.RRF_K + rank)
by_hybrid = [i for i, _ in fused.most_common()]

step("2. Top 5 by each method")
print(f"    {'rank':<5}{'keyword (score)':<42}{'meaning (score)':<42}hybrid (score)")
for r in range(5):
    k, m, h = by_keyword[r], by_meaning[r], by_hybrid[r]
    kw = f"{titles[k][:30]} ({keyword[k]:.2f})" if keyword[k] > 0 else "(no shared words)"
    print(f"    {r + 1:<5}{kw:<42}{titles[m][:30] + f' ({meaning[m]:.2f})':<42}{titles[h][:30]} ({fused[h]:.4f})")

step("3. Why keyword search matched what it did")
terms = chatbot.words(question)
print(f"    Question words after cleaning (stop words removed, light stemming): {terms}")
for i in [i for i in by_keyword if keyword[i] > 0][:3]:
    shared = [t for t in terms if t in retriever.docs[i]]
    print(f"    '{titles[i][:40]}' matched on {shared}")
if not any(keyword[i] > 0 for i in by_keyword):
    print("    No section shares a word with the question, so only meaning search can find anything.")

print("""
What to notice
  • Keyword search only scores sections that share the question's (rare) words. Casual wording often shares none.
  • Meaning search always returns a ranking, even for nonsense, so it needs a sensible cut-off (top 5 here).
  • Hybrid rewards sections that do well in either list, and best of all in both: a section ranked 1st by one
    method and 3rd by the other beats one ranked 2nd by only one.
  • This step decides what the model can possibly know. If the right section isn't in the top 5, no prompt
    wording can fix the answer.

Try
  • python -m labs.lab3_retrieval "Loaded Cheese Fries"            (an exact name: keywords shine)
  • python -m labs.lab3_retrieval "when do we get slammed?"        (casual wording: meaning shines)
  • python -m labs.lab3_retrieval "tonight"                        (one word: what happens?)
""")
