"""Official anthropic SDK. Switching to it is a config change only. Cost comes from config/llm_pricing.yaml."""
from __future__ import annotations

import time
from typing import Any

import anthropic

from territory.llm.base import MAX_RETRIES, TIMEOUT_S, LLMError, parse_json
from territory.llm.pricing import cost_from_pricing


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, client: anthropic.Anthropic | None = None, pricing: dict | None = None,
                 sleep=time.sleep):
        self.model = model
        self.pricing = pricing
        self._sleep = sleep
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_S, max_retries=0)

    def complete(self, task: str, system: str, messages: list[dict], json_schema: dict | None,
                 model: str | None = None) -> dict[str, Any]:
        m = model or self.model
        sysmsg = system
        if json_schema is not None:
            import json
            sysmsg += "\n\nReply with ONLY a JSON object matching this JSON Schema:\n" + json.dumps(json_schema)
        t0 = time.monotonic()
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self.client.messages.create(model=m, max_tokens=4096, system=sysmsg,
                                                messages=messages)
                break
            except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError,
                    anthropic.APITimeoutError) as exc:
                if attempt == MAX_RETRIES:
                    raise LLMError(f"{type(exc).__name__} after {MAX_RETRIES} retries: {exc}") from exc
                self._sleep(2 ** attempt)
            except anthropic.APIStatusError as exc:
                raise LLMError(f"HTTP {exc.status_code}: {str(exc)[:300]}") from exc
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        i, o = r.usage.input_tokens, r.usage.output_tokens
        return {"output": parse_json(text), "raw": text, "provider": self.name, "model": m,
                "input_tokens": i, "output_tokens": o, "cost_usd": cost_from_pricing(m, i, o, self.pricing),
                "latency_ms": int((time.monotonic() - t0) * 1000)}
