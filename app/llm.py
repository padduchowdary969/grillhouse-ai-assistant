"""One interface for every model the copilot can call, so tasks can be routed and compared by cost and latency.

    from app.llm import get_provider
    reply = get_provider("local").complete(system="...", user="...")
    print(reply.text, reply.latency_s, reply.cost_usd)

Providers:
  local    Ollama on this machine (free; default model qwen3:8b)
  bedrock  Claude via AWS Bedrock (added in Phase 2 once the AWS account is set up)
"""

import json
import os
import time
import urllib.request
from dataclasses import dataclass

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


@dataclass
class Reply:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float = 0.0


class OllamaProvider:
    """Local open-weights model through Ollama's chat API."""

    name = "local"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("GRILLHOUSE_MODEL", "qwen3:8b")

    def complete(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = 1024,
                 json_schema: dict | None = None) -> Reply:
        body = {"model": self.model, "stream": False, "think": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": temperature, "num_ctx": 16384, "num_predict": max_tokens}}
        if json_schema:
            body["format"] = json_schema  # Ollama constrains the output to this JSON schema
        request = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        start = time.time()
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.load(response)
        return Reply(text=data["message"]["content"].strip(), model=self.model,
                     input_tokens=data.get("prompt_eval_count", 0), output_tokens=data.get("eval_count", 0),
                     latency_s=round(time.time() - start, 2))


PROVIDERS = {"local": OllamaProvider}


def get_provider(name: str | None = None):
    name = name or os.environ.get("GRILLHOUSE_PROVIDER", "local")
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; available: {', '.join(PROVIDERS)}")
    return PROVIDERS[name]()
