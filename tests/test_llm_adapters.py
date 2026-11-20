"""Provider adapters with mocked HTTP (no real API is ever called), the structured-output wrapper and the factory."""
import json

import httpx2
import openai
import anthropic
import pytest
from pydantic import BaseModel

from territory.config import ClientConfig, load_client
from territory.llm.anthropic_provider import AnthropicProvider
from territory.llm.base import LLMError, schema_of, structured
from territory.llm.factory import get_provider
from territory.llm.fake import FakeProvider
from territory.llm.openai_compatible import REFERER, OpenAICompatibleProvider
from territory.llm.pricing import cost_from_pricing

OR = "https://openrouter.ai/api/v1"


class Mock:
    """An offline HTTP transport for the SDK clients (the SDKs use httpx2). Records every request; never touches the network."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return r

    @property
    def call_count(self):
        return len(self.requests)

    def http(self):
        return httpx2.Client(transport=httpx2.MockTransport(self.handler))


def resp(status, body):
    return httpx2.Response(status, json=body)


def oa(mock, base, sleep=lambda s: None, model="vendor/model"):
    sdk = openai.OpenAI(base_url=base, api_key="k", http_client=mock.http(), max_retries=0,
                        default_headers=({"HTTP-Referer": REFERER, "X-Title": "Territory Signals"} if "openrouter" in base else {}))
    return OpenAICompatibleProvider(base, "k", model, client=sdk, sleep=sleep)


def chat_reply(content, cost=0.0007, model="vendor/model", prompt=100, completion=50, usage_extra=True):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}
    if usage_extra:
        usage["cost"] = cost
    return {"id": "x", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": usage}


class Out(BaseModel):
    title: str
    n: int


SCHEMA = schema_of(Out)


def test_openrouter_request_shape_headers_and_cost():
    m = Mock(resp(200, chat_reply('{"title":"a","n":1}')))
    r = oa(m, OR).complete("t", "sys", [{"role": "user", "content": "hi"}], SCHEMA)
    req = m.requests[0]
    body = json.loads(req.content)
    assert body["provider"] == {"data_collection": "deny", "require_parameters": True}
    assert body["usage"] == {"include": True}
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert req.headers["HTTP-Referer"] == REFERER == "https://kaiser-team-signals.mike-1d7.workers.dev"
    assert req.headers["X-Title"] == "Territory Signals"
    assert req.headers["Authorization"] == "Bearer k"
    assert str(req.url) == f"{OR}/chat/completions"
    assert r["output"] == {"title": "a", "n": 1} and r["cost_usd"] == 0.0007
    assert (r["input_tokens"], r["output_tokens"], r["provider"], r["model"]) == (100, 50, "openai_compatible", "vendor/model")
    assert r["latency_ms"] >= 0


@pytest.mark.parametrize("base", ["https://api.x.ai/v1", "https://api.openai.com/v1", "http://localhost:11434/v1"])
def test_other_openai_compatible_hosts_get_no_openrouter_fields(base):
    m = Mock(resp(200, chat_reply('{"title":"a","n":1}', usage_extra=False)))
    r = oa(m, base).complete("t", "s", [{"role": "user", "content": "x"}], SCHEMA)
    body = json.loads(m.requests[0].content)
    assert "provider" not in body and "usage" not in body
    assert "HTTP-Referer" not in m.requests[0].headers
    assert str(m.requests[0].url) == f"{base}/chat/completions"
    assert r["cost_usd"] is None                      # only OpenRouter reports cost; never guessed


def test_retries_429_and_5xx_with_backoff_then_succeeds():
    sleeps = []
    m = Mock(resp(429, {"error": {"message": "slow down"}}), resp(503, {"error": {"message": "down"}}),
             resp(200, chat_reply('{"title":"a","n":1}')))
    r = oa(m, OR, sleep=sleeps.append).complete("t", "s", [{"role": "user", "content": "x"}], SCHEMA)
    assert m.call_count == 3 and sleeps == [1, 2] and r["output"]["n"] == 1


def test_gives_up_after_three_retries_and_does_not_retry_4xx():
    m = Mock(resp(500, {"error": {"message": "x"}}))
    with pytest.raises(LLMError):
        oa(m, OR).complete("t", "s", [{"role": "user", "content": "x"}], SCHEMA)
    assert m.call_count == 4                       # first try + 3 retries
    m = Mock(resp(400, {"error": {"message": "bad"}}))
    with pytest.raises(LLMError):
        oa(m, OR).complete("t", "s", [{"role": "user", "content": "x"}], SCHEMA)
    assert m.call_count == 1


def test_timeout_is_60_seconds():
    p = OpenAICompatibleProvider(OR, "k", "m")
    assert p.client.timeout == 60 and p.client.max_retries == 0


def an(mock, pricing, model="claude-x"):
    sdk = anthropic.Anthropic(api_key="k", http_client=mock.http(), max_retries=0)
    return AnthropicProvider("k", model, client=sdk, pricing=pricing, sleep=lambda s: None)


def test_anthropic_adapter_maps_reply_and_prices_from_the_config_file():
    ok = resp(200, {"id": "m", "type": "message", "role": "assistant", "model": "claude-x", "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": '{"title":"a","n":2}'}], "usage": {"input_tokens": 1000, "output_tokens": 500}})
    m = Mock(ok)
    pricing = {"claude-x": {"input_per_m": 1.0, "output_per_m": 5.0}}
    r = an(m, pricing).complete("t", "sys", [{"role": "user", "content": "hi"}], SCHEMA)
    body = json.loads(m.requests[0].content)
    assert body["model"] == "claude-x" and "JSON Schema" in body["system"] and body["messages"] == [{"role": "user", "content": "hi"}]
    assert str(m.requests[0].url) == "https://api.anthropic.com/v1/messages"
    assert r["output"] == {"title": "a", "n": 2}
    assert r["cost_usd"] == pytest.approx(0.0035) and (r["input_tokens"], r["output_tokens"]) == (1000, 500)
    # a model with no price on file: cost unknown (None), never guessed
    r2 = an(Mock(ok), {}).complete("t", "sys", [{"role": "user", "content": "hi"}], SCHEMA)
    assert r2["cost_usd"] is None


def test_anthropic_retries_429_then_gives_up():
    ok = resp(200, {"id": "m", "type": "message", "role": "assistant", "model": "claude-x", "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "{}"}], "usage": {"input_tokens": 1, "output_tokens": 1}})
    m = Mock(resp(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}}), ok)
    assert an(m, {}).complete("t", "s", [{"role": "user", "content": "x"}], None)["output"] == {}
    m = Mock(resp(529, {"type": "error", "error": {"type": "overloaded_error", "message": "x"}}))
    with pytest.raises(LLMError):
        an(m, {}).complete("t", "s", [{"role": "user", "content": "x"}], None)
    assert m.call_count == 4


def test_pricing_function_and_missing_model():
    assert cost_from_pricing("m", 2_000_000, 1_000_000, {"m": {"input_per_m": 1, "output_per_m": 4}}) == 6.0
    assert cost_from_pricing("nope", 10, 10, {"m": {"input_per_m": 1, "output_per_m": 4}}) is None


def test_fake_provider_is_deterministic_and_offline():
    f = FakeProvider(replies=[{"title": "a", "n": 1}])
    r = f.complete("t", "s", [{"role": "user", "content": "hello"}], None)
    assert r["output"] == {"title": "a", "n": 1} and r["provider"] == "fake" and f.calls[0]["task"] == "t"


# ---- structured output: validate with pydantic, retry once with the error, then give up ----------
def test_structured_valid_first_time():
    f = FakeProvider(replies=[{"title": "a", "n": 1}])
    res = structured(f, "t", "s", "u", Out)
    assert res.ok and res.value.n == 1 and res.calls == 1


def test_structured_retries_once_with_the_validation_error_appended():
    f = FakeProvider(replies=["not json at all", {"title": "a", "n": 3}])
    res = structured(f, "t", "s", "u", Out)
    assert res.ok and res.calls == 2 and res.value.n == 3
    second = f.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-2]["content"] == "not json at all"
    assert second[-1]["role"] == "user" and "invalid" in second[-1]["content"]
    assert res.input_tokens > 0 and res.cost_usd == pytest.approx(0.002)       # both calls counted


def test_structured_second_failure_is_reported_not_raised():
    f = FakeProvider(replies=[{"title": "a"}, {"title": "a", "n": "x"}])
    res = structured(f, "t", "s", "u", Out)
    assert not res.ok and res.value is None and res.calls == 2 and "n" in res.error


def test_structured_unknown_cost_stays_unknown():
    class NoCost(FakeProvider):
        def complete(self, *a, **k):
            r = super().complete(*a, **k)
            r["cost_usd"] = None
            return r
    res = structured(NoCost(replies=[{"title": "a", "n": 1}]), "t", "s", "u", Out)
    assert res.ok and res.cost_usd is None


def test_schema_keeps_a_field_named_title_and_is_strict():
    s = schema_of(Out)
    assert "title" in s["properties"] and s["additionalProperties"] is False and s["required"] == ["title", "n"]


# ---- skip cleanly: disabled, no key, no config -------------------------------------------------------
def client_with(**llm):
    data = load_client("kaiser-team").model_dump()
    data["llm"] = {**data["llm"], **llm}
    return ClientConfig.model_validate(data)


def test_factory_skips_when_disabled_or_key_missing():
    p, why = get_provider(client_with(enabled=False), env={"LLM_API_KEY": "k"})
    assert p is None and "enabled" in why
    p, why = get_provider(client_with(enabled=True), env={})
    assert p is None and "LLM_API_KEY" in why
    p, why = get_provider(client_with(), env={"LLM_API_KEY": "k"})
    assert p.name == "openai_compatible" and why is None


def test_switching_provider_is_a_config_change():
    p, _ = get_provider(client_with(provider="anthropic", base_url=None, model="claude-x"), env={"LLM_API_KEY": "k"})
    assert p.name == "anthropic"
    p, _ = get_provider(client_with(base_url="http://localhost:11434/v1", model="llama3"), env={"LLM_API_KEY": "ollama"})
    assert p.name == "openai_compatible" and "localhost" in p.base_url
