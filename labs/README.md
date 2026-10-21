# Labs: how LLMs work with data

Six short, hands-on scripts that open up the Grill House AI Assistant one step at a time. Each prints what
happens inside, then lists what to notice and things to try. They run on the **synthetic demo data** and a
**local model**, so they're free and nothing leaves your computer.

## Before you start

```bash
docker compose up -d                  # demo database (Labs 5 and 6)
ollama pull qwen3:8b                  # the model that writes answers
ollama pull nomic-embed-text          # the model that turns text into numbers
python -m pipelines.run_all --no-db   # demo reports (Labs 1-4), if you haven't built them
```

## The big idea

An LLM knows nothing about the shop. It's a very good **reader and writer** that only sees the text you give it
for each question. Every "LLM + data" system is a way of choosing **which data goes in front of the model, and in
what form**:

```
question → your code finds the right data → prompt (rules + data + question) → model → answer
                     ▲
          retrieval (Labs 2-3) or a database query (Lab 5)
```

| Lab | Run | Idea | Key result from 21 Oct 2026 |
|---|---|---|---|
| 1 | `python -m labs.lab1_what_the_model_sees` | The prompt: everything the model knows for one question | ~2,100 tokens of rules and facts behind a one-line answer |
| 2 | `python -m labs.lab2_embeddings` | Embeddings: meaning as numbers | "animal products" found the vegan menu with no shared words, but a sentence sharing "slammed" fooled it |
| 3 | `python -m labs.lab3_retrieval` | Retrieval: keyword vs meaning vs hybrid | "moan" matched "When people order" by keyword (on "people"); meaning found Customer ratings |
| 4 | `python -m labs.lab4_grounding` | Grounding: why models make things up | Without facts: "150–200 orders". With facts: 20, which is right |
| 5 | `python -m labs.lab5_text_to_sql` | Tools: the model writes SQL, your code runs it | Rainy 16.1 vs dry 12.8 orders; 5 of 5 dangerous queries blocked |
| 6 | `python -m labs.lab6_evaluation` | Evaluation: measure before you trust | Business rules in the prompt: 7/8 with, 4/8 without |

Most labs take a question: `python -m labs.lab3_retrieval "which grub barely sells?"`.

## Lab by lab

### 1 · What the model sees
**Learn:** tokens, the context window, the system prompt, and that the model's knowledge is only the text in
front of it.
**Check yourself:**
- Which parts of the prompt are the same for every question, and which change?
- Why does a prompt full of numbers use more tokens per character than plain English?
- If you ask "How many staff do we have?", which facts does search pick, and what should the model say?

### 2 · Embeddings
**Learn:** an embedding is a list of numbers (768 here) describing meaning; cosine similarity compares two lists.
**Check yourself:**
- Why can a sentence with no shared words score highest?
- Why did the "paint" sentence beat the real answer for "slammed"? What does that tell you about using
  embeddings alone?

### 3 · Retrieval
**Learn:** chunking, TF-IDF keyword scoring, dense (meaning) search, reciprocal rank fusion, top-k.
**Check yourself:**
- When does keyword search beat meaning search? (Try an exact dish name.)
- Why does hybrid search add `1 / (60 + rank)` from each list instead of adding the raw scores?
- If the right section isn't in the top 5, can a better prompt fix the answer?

### 4 · Grounding
**Learn:** hallucination, grounding instructions, refusing when the facts are missing.
**Check yourself:**
- Why did case A sound confident when it had no data at all?
- What one sentence of the instructions changed case B?
- Retrieval brought the wrong section in case C. Which lab's technique prevents that?

### 5 · Text-to-SQL
**Learn:** tool use. The model writes a query from table descriptions, your code validates and runs it, and the
model explains the exact result. Defence in depth: query validation plus a read-only database user.
**Check yourself:**
- Where do the numbers in the final answer come from: the model or the database?
- What happens when the model's first query has an error?
- Why are there two separate safety layers?

### 6 · Evaluation
**Learn:** golden sets, execution-match scoring, changing one thing at a time, small-sample noise.
**Check yourself:**
- Which questions failed without the business rules, and which rule would each have needed?
- Why score the query's *result* rather than compare SQL text?
- With 8 questions, how much is one flip worth? Why does the real set have 50?

## Glossary

| Term | Meaning |
|---|---|
| **Token** | A piece of a word; models read and write in tokens and are priced per token |
| **Context window** | The most tokens the model can see at once (here 16,384) |
| **System prompt** | Standing instructions sent with every question |
| **Embedding** | Text turned into a list of numbers that captures meaning |
| **Cosine similarity** | How closely two embeddings point the same way (higher = more similar) |
| **Chunking** | Splitting documents into sections small enough to retrieve |
| **RAG** | Retrieval-augmented generation: search for the right facts, then let the model answer from them |
| **Hybrid search / RRF** | Combining keyword and meaning rankings; reciprocal rank fusion merges them by rank |
| **Grounding** | Making the model answer only from the facts it was given |
| **Hallucination** | A fluent, confident answer that isn't supported by any facts |
| **Tool use / Text-to-SQL** | The model writes a call (here a SQL query) that your code runs |
| **Golden set** | Questions with known correct answers, used to score a system |
| **Execution match** | A SQL answer counts as correct when its result matches the reference result |
| **Fine-tuning** | Retraining a model on examples; changes behaviour or style, and is the wrong tool for teaching it facts |

## Where this lives in the real app

| Lab | Code |
|---|---|
| 1, 3, 4 | [`app/chatbot.py`](../app/chatbot.py): `build_knowledge`, `Retriever`, `build_messages` |
| 2 | [`app/chatbot.py`](../app/chatbot.py) `embed`, [`app/documents.py`](../app/documents.py) |
| 5 | [`app/text_to_sql.py`](../app/text_to_sql.py), [`app/sql_tool.py`](../app/sql_tool.py) |
| 6 | [`evals/`](../evals/), [docs/EVALUATION.md](../docs/EVALUATION.md) |
