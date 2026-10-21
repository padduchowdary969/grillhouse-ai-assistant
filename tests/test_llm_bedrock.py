"""The Bedrock provider builds the right request. Runs against a fake client (no AWS account or network needed);
skipped where the optional anthropic[bedrock] package isn't installed (requirements/bedrock.txt)."""

from types import SimpleNamespace

import pytest

anthropic = pytest.importorskip("anthropic")

from app import llm  # noqa: E402


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn", stop_details=None, model=kwargs["model"],
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text='{"sql": "SELECT 1"}')],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200))


@pytest.fixture
def provider(monkeypatch):
    fake = FakeMessages()
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(beta=SimpleNamespace(messages=fake))

    monkeypatch.setattr(anthropic, "AnthropicBedrockMantle", fake_client)
    p = llm.BedrockProvider(region="eu-west-2")
    p.fake, p.client_kwargs = fake, captured
    return p


def test_client_uses_region_and_refusal_fallback(provider):
    assert provider.client_kwargs["aws_region"] == "eu-west-2"
    assert len(provider.client_kwargs["middleware"]) == 1  # client-side fallback, as Bedrock has no server-side one


def test_request_shape(provider):
    reply = provider.complete("system rules", "question", max_tokens=500,
                              json_schema={"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]})
    call = provider.fake.calls[0]
    assert call["model"] == "anthropic.claude-opus-5-5"
    assert "temperature" not in call                    # Opus 5.5 rejects sampling parameters
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert call["max_tokens"] > 500                     # headroom for thinking
    assert reply.text == '{"sql": "SELECT 1"}'          # thinking blocks are skipped
    assert reply.cost_usd == pytest.approx((1000 * 4 + 200 * 20) / 1e6)


def test_refusal_raises(provider):
    provider.fake.create = lambda **kw: SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"))
    with pytest.raises(RuntimeError, match="declined"):
        provider.complete("s", "q")
