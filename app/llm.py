"""One interface for every model the assistant can call, so tasks can be routed and compared by cost and latency.

    from app.llm import get_provider
    reply = get_provider("bedrock").complete(system="...", user="...")
    print(reply.text, reply.latency_s, reply.cost_usd)

Providers:
  local    Ollama on this machine (free; default model qwen3:8b)
  bedrock  Claude via Amazon Bedrock (default Claude Opus 5.5), using AWS credentials from the environment
           (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION, e.g. in .env) or the AWS credential chain

Check a provider works:
    python -m app.llm bedrock
"""

import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass

from app import config  # noqa: F401  (loads .env, including AWS credentials)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# USD per million tokens (input, output), Claude API list prices. Bedrock's own pricing is set by AWS (regional
# endpoints add 10%), so treat these as estimates and check the AWS bill for actual spend.
PRICES = {"anthropic.claude-opus-5-5": (4.00, 20.00), "anthropic.claude-opus-4-8": (5.00, 25.00),
          "anthropic.claude-sonnet-5-5": (2.00, 10.00), "anthropic.claude-haiku-5-5": (0.10, 0.50)}


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


class BedrockProvider:
    """Claude on Amazon Bedrock through the Messages-API (Mantle) endpoint.

    Claude Opus 5.5 always thinks before answering, so depth is set with `effort` (low/medium/high) rather than
    temperature, which this model doesn't accept. If Bedrock's safety checks decline a request, the client-side
    fallback middleware retries it on Claude Opus 4.8 (Bedrock has no server-side fallback).
    """

    name = "bedrock"
    FALLBACK_MODEL = "anthropic.claude-opus-4-8"

    def __init__(self, model: str | None = None, effort: str | None = None, region: str | None = None):
        from anthropic import AnthropicBedrockMantle, BetaRefusalFallbackMiddleware

        self.model = model or os.environ.get("GRILLHOUSE_BEDROCK_MODEL", "anthropic.claude-opus-5-5")
        self.effort = effort or os.environ.get("GRILLHOUSE_BEDROCK_EFFORT", "medium")
        self.client = AnthropicBedrockMantle(
            aws_region=region or os.environ.get("AWS_REGION", "eu-west-2"),
            middleware=[BetaRefusalFallbackMiddleware([{"model": self.FALLBACK_MODEL}])])

    def complete(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = 1024,
                 json_schema: dict | None = None) -> Reply:
        from anthropic import BetaFallbackState

        output_config: dict = {"effort": self.effort}
        if json_schema:
            output_config["format"] = {"type": "json_schema",
                                       "schema": {**json_schema, "additionalProperties": False}}
        start = time.time()
        with BetaFallbackState():  # one state per conversation; each call here is its own conversation
            response = self.client.beta.messages.create(
                model=self.model,
                # Thinking tokens count towards max_tokens, so leave headroom above the visible answer
                max_tokens=max_tokens + 8000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
            )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined the request ({getattr(response.stop_details, 'category', None)})")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        price_in, price_out = PRICES.get(response.model, PRICES[self.model] if self.model in PRICES else (0, 0))
        cost = (response.usage.input_tokens * price_in + response.usage.output_tokens * price_out) / 1_000_000
        return Reply(text=text, model=response.model, input_tokens=response.usage.input_tokens,
                     output_tokens=response.usage.output_tokens, latency_s=round(time.time() - start, 2),
                     cost_usd=round(cost, 6))


PROVIDERS = {"local": OllamaProvider, "bedrock": BedrockProvider}


def get_provider(name: str | None = None):
    name = name or os.environ.get("GRILLHOUSE_PROVIDER", "local")
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; available: {', '.join(PROVIDERS)}")
    return PROVIDERS[name]()


if __name__ == "__main__":
    provider = get_provider(sys.argv[1] if len(sys.argv) > 1 else None)
    reply = provider.complete("Reply in one short sentence.", "Say hello to the Grill House team.", max_tokens=100)
    print(f"{reply.model}: {reply.text}\n{reply.input_tokens} in / {reply.output_tokens} out tokens, "
          f"{reply.latency_s}s, ~${reply.cost_usd:.4f}")
