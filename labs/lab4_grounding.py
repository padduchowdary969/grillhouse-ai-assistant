"""Lab 4: grounding, or why models make things up and what stops it.

The same question, asked four ways:
  A  no rules, no facts        the model answers from general knowledge: it has none about this shop
  B  grounding rule, no facts  "use only the facts given; otherwise say you don't know"
  C  grounding rule, wrong facts (search picked the wrong section)
  D  grounding rule, right facts

    python -m labs.lab4_grounding
"""

from labs._common import chat, need_demo_reports, need_ollama, show, step, title

need_ollama()
need_demo_reports()
from app import chatbot  # noqa: E402

question = "How many orders should we expect on Saturday night?"
title(f"Lab 4 · Grounding: {question!r}")

GROUNDED = ("You are the business assistant for a takeaway. Answer using only the facts provided. If they don't "
            "contain the answer, say \"I don't have that information\". Keep it to one or two sentences.")
right_facts = chatbot.next_nights_forecast()
wrong_facts = next(body for t, body in chatbot.build_knowledge() if t == "Opening hours")

cases = [
    ("A · no rules, no facts", "You are a helpful assistant. Keep it to one or two sentences.", question),
    ("B · grounding rule, no facts", GROUNDED, question),
    ("C · grounding rule, wrong facts", GROUNDED, f"Facts:\n{wrong_facts}\n\nQuestion: {question}"),
    ("D · grounding rule, right facts", GROUNDED, f"Facts:\n{right_facts}\n\nQuestion: {question}"),
]
truth = next((line for line in right_facts.splitlines() if "Saturday" in line), "")

for name, system, user in cases:
    step(name)
    reply = chat(system, user, max_tokens=120)
    show(reply["text"])

step("The true answer, from the forecast")
show(truth.strip("- "))

print("""
What to notice
  • A: with nothing to go on, the model still answers. It produces something plausible-sounding (often a
    made-up number or a generic "it depends"). That's a hallucination: fluent, confident, unsupported.
  • B: one instruction turns guessing into "I don't have that information". Refusing is the correct answer here.
  • C: with the wrong facts on the page, a well-instructed model should still refuse; a weaker one may
    stretch the opening hours into an answer. Retrieval quality (Lab 3) matters as much as the prompt.
  • D: with the right facts, the answer is specific and matches the forecast exactly.

The rule of thumb: the model is a reader and a writer, not a database. Put the right facts in front of it and
tell it to stick to them.

Try
  • Edit `question` to something only the reviews could answer ("What do customers complain about?").
  • Remove the last sentence of GROUNDED ("If they don't contain...") and rerun case C.
""")
