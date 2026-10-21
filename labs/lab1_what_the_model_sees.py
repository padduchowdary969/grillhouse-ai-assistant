"""Lab 1: what the model actually sees.

An LLM knows nothing about the shop. For every question, the assistant builds one block of text (the prompt):
rules + today's date + facts found by search + the question. This lab prints that text, counts its tokens,
and then shows the answer the model writes from it.

    python -m labs.lab1_what_the_model_sees
    python -m labs.lab1_what_the_model_sees "What should I prep for Saturday night?"
"""

import sys

from labs._common import chat, need_demo_reports, need_ollama, show, step, title

need_ollama()
need_demo_reports()
from app import chatbot  # noqa: E402  (imported after the checks so errors are friendly)

question = " ".join(sys.argv[1:]) or "Which night of the week is busiest?"
title(f"Lab 1 · What the model sees for: {question!r}")

retriever = chatbot.Retriever(chatbot.build_knowledge())
messages = chatbot.build_messages(question, retriever, history=[])
system, user = messages[0]["content"], messages[-1]["content"]

step("1. The instructions (system prompt): the same for every question, plus today's date and shop facts")
show(system)

step("2. The facts search picked for this question (section titles only)")
for line in user.splitlines():
    if line.startswith("### "):
        print("    •", line[4:])

step("3. The full message the model receives (shortened)")
show(user, limit=1500)

reply = chat(system, user)
step("4. Size of the prompt")
print(f"    {len(system) + len(user):,} characters → {reply['tokens_in']:,} tokens "
      f"(about {(len(system) + len(user)) / max(reply['tokens_in'], 1):.1f} characters per token;"
      " numbers and tables split into more tokens than plain English, which averages about 4)")
print(f"    The model's context window here is 16,384 tokens, so this prompt uses "
      f"{100 * reply['tokens_in'] / 16384:.0f}% of it.")

step("5. The model's answer (written only from the text above)")
show(reply["text"])
print(f"\n    {reply['tokens_out']} tokens written in {reply['seconds']}s")

print("""
What to notice
  • The model never touched a database or a file: everything it "knows" is in steps 1 and 3.
  • Search decided which facts made it onto the page. Wrong facts in → wrong answer out (see Lab 4).
  • Tokens are pieces of words. Prompt size drives speed and, on paid models, cost.

Try
  • Ask something the facts can't answer ("How many staff do we have?") and look at what search picked.
  • Ask "tonight" vs "this month" and compare which sections appear.
""")
