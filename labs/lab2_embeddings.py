"""Lab 2: embeddings, or how a computer measures "means the same thing".

An embedding model turns a piece of text into a list of numbers (here 768 of them). Texts with similar meaning
get similar lists, even with no words in common. Similarity is measured with cosine similarity: 1.0 means
"pointing the same way", around 0.3-0.4 means unrelated for this model.

    python -m labs.lab2_embeddings
    python -m labs.lab2_embeddings "anything for someone who doesn't eat meat?"
"""

import sys

from labs._common import need_ollama, step, title

need_ollama()
from app.chatbot import cosine, embed, words  # noqa: E402

query = " ".join(sys.argv[1:]) or "When do we get slammed?"
candidates = [
    "Busiest hours: Saturday night between 04:00 and 06:00",       # same meaning, different words
    "Peak times for orders across the week",                        # same meaning
    "Quiet nights: Monday and Tuesday",                              # related, opposite
    "Customer complaints: food arrived cold",                        # different topic
    "Vegan options: veggie wrap, sweet potato fries",                # different topic
    "The shop is slammed with a new paint colour on the door",       # a trap: shares "slammed", different meaning
]

title(f"Lab 2 · Which sentences mean the same as {query!r}?")

step("1. A sentence becomes numbers")
vector = embed([f"search_query: {query}"])[0]
print(f"    {len(vector)} numbers, starting: {', '.join(f'{x:+.3f}' for x in vector[:6])} ...")

step("2. Similarity by meaning (embeddings) vs by shared words (keywords)")
vectors = embed([f"search_document: {c}" for c in candidates])
query_words = set(words(query))
rows = sorted(((cosine(vector, v), len(query_words & set(words(c))), c) for c, v in zip(candidates, vectors)), reverse=True)
print(f"    {'meaning':>8}  {'shared words':>12}   sentence")
for score, shared, text in rows:
    bar = "█" * int(max(score - 0.3, 0) * 40)
    print(f"    {score:8.3f}  {shared:12d}   {text}  {bar}")

top_score, top_shared, top_text = rows[0]
step("3. What happened")
if top_shared and "paint" in top_text:
    print("""    The sentence about paint came first, just because it shares the rare word "slammed".
    Small embedding models still lean on surface words. That's why the assistant uses HYBRID search
    (keywords + meaning, Lab 3), and why chunks get descriptive titles ("busy, quiet, peak times").""")
elif top_shared == 0:
    print(f"""    The best match shares no words with the question: {top_text!r}.
    That's the point of embeddings: matching by meaning, not spelling.""")
else:
    print(f"    The best match was {top_text!r}.")

print("""
What to notice
  • Embeddings capture meaning, but not perfectly: they can be fooled by an unusual shared word.
  • Scores are relative: the order matters, not the exact numbers.
  • Neither keywords nor embeddings is enough alone; combining them (Lab 3) is the standard fix.

Try
  • python -m labs.lab2_embeddings "anything without animal products?"   (no shared words, still finds vegan)
  • python -m labs.lab2_embeddings "what do people moan about?"
  • Delete the paint sentence from `candidates` and run the default question again.
""")
