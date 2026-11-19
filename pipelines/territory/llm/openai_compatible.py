"""openai SDK with a configurable base_url: OpenRouter, xAI, OpenAI, Ollama. This is the adapter the client uses."""
from __future__ import annotations

import time
from typing import Any

import openai

from territory.llm.base import MAX_RETRIES, TIMEOUT_S, LLMError, parse_json

OPENROUTER_HOST = "openrouter.ai"
REFERER = "https://kaiser-team-signals.mike-1d7.workers.dev"
TITLE = "Territory Signals"


def _usage_cost(usage: Any) -> float | None:
    """OpenRouter reports cost in usage.cost when usage: {include: true} is sent."""
    if usage is None:
        return None
    c = getattr(usage, "cost", None)
    if c is None and getattr(usage, "model_extra", None):
        c = usage.model_extra.get("cost")
    return float(c) if c is not None else None


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str, client: openai.OpenAI | None = None,
                 sleep=time.sleep):
        self.base_url = base_url
        self.model = model
        self.is_openrouter = OPENROUTER_HOST in base_url
        self._sleep = sleep
        headers = {"HTTP-Referer": REFERER, "X-Title": TITLE} if self.is_openrouter else {}
        self.client = client or openai.OpenAI(base_url=base_url, api_key=api_key or "none", timeout=TIMEOUT_S,
                                              max_retries=0, default_headers=headers)

    def request_kwargs(self, task: str, system: str, messages: list[dict], json_schema: dict | None,
                       model: str | None) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
        }
        if json_schema is not None:
            kw["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": task, "strict": True, "schema": json_schema}}
        if self.is_openrouter:
            kw["extra_body"] = {"provider": {"data_collection": "deny", "require_parameters": True},
                                "usage": {"include": True}}
        return kw

    def complete(self, task: str, system: str, messages: list[dict], json_schema: dict | None,
                 model: str | None = None) -> dict[str, Any]:
        kw = self.request_kwargs(task, system, messages, json_schema, model)
        t0 = time.monotonic()
        last: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self.client.chat.completions.create(**kw)
                break
            except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError,
                    openai.APITimeoutError) as exc:
                last = exc
                if attempt == MAX_RETRIES:
                    raise LLMError(f"{type(exc).__name__} after {MAX_RETRIES} retries: {exc}") from exc
                self._sleep(2 ** attempt)
            except openai.APIStatusError as exc:
                raise LLMError(f"HTTP {exc.status_code}: {str(exc)[:300]}") from exc
        else:  # pragma: no cover
            raise LLMError(str(last))
        text = (r.choices[0].message.content if r.choices else None) or ""
        u = r.usage
        return {
            "output": parse_json(text), "raw": text, "provider": self.name, "model": getattr(r, "model", None) or kw["model"],
            "input_tokens": getattr(u, "prompt_tokens", 0) or 0, "output_tokens": getattr(u, "completion_tokens", 0) or 0,
            "cost_usd": _usage_cost(u) if self.is_openrouter else None,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
