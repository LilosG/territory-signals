"""Provider interface and the structured-output wrapper (validate with pydantic, retry once, then give up)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

TIMEOUT_S = 60
MAX_RETRIES = 3        # for 429 / 5xx, with backoff


class LLMError(RuntimeError):
    """The provider could not return a response (after retries)."""


class ProviderConfigError(LLMError):
    """Missing key, unknown provider, or llm.enabled is false."""


class Provider(Protocol):
    name: str

    def complete(self, task: str, system: str, messages: list[dict], json_schema: dict | None,
                 model: str | None = None) -> dict[str, Any]:
        """Returns {output, provider, model, input_tokens, output_tokens, cost_usd, latency_ms, raw}.
        `output` is the parsed JSON object when the reply parses, else None; `raw` is the reply text.
        `cost_usd` is None when the price is unknown (never guessed)."""


def parse_json(text: str | None) -> Any:
    if text is None:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        return json.loads(t)
    except (ValueError, TypeError):
        # tolerate prose around one JSON object
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except ValueError:
                return None
        return None


def schema_of(model_cls: type[BaseModel]) -> dict:
    """JSON Schema for response_format. Strict-mode providers need additionalProperties=false and every key required."""
    schema = model_cls.model_json_schema()

    def tidy(node):
        """Walk schema nodes (not the field-name maps, where a field may itself be called "title")."""
        if isinstance(node, list):
            for v in node:
                tidy(v)
            return
        if not isinstance(node, dict):
            return
        for k in ("minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "title", "default"):
            node.pop(k, None)         # strict mode rejects these; pydantic enforces them after the call
        props = node.get("properties")
        if isinstance(props, dict):
            node["additionalProperties"] = False
            node["required"] = list(props)
            for v in props.values():
                tidy(v)
        for k in ("items", "anyOf", "allOf", "oneOf"):
            if k in node:
                tidy(node[k])
        for v in node.get("$defs", {}).values():
            tidy(v)
    tidy(schema)
    return schema


@dataclass
class StructuredResult:
    ok: bool
    value: BaseModel | None
    error: str | None
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0       # None = unknown
    latency_ms: int = 0
    calls: int = 0
    raw: str | None = None
    warnings: list[str] = field(default_factory=list)


def structured(provider: Provider, task: str, system: str, user: str, model_cls: type[BaseModel],
               model: str | None = None) -> StructuredResult:
    """One call, validated with pydantic. On invalid JSON / schema failure, retry ONCE with the error appended.
    A second failure returns ok=False (the caller stores status=invalid and shows nothing)."""
    schema = schema_of(model_cls)
    messages = [{"role": "user", "content": user}]
    tot_in = tot_out = latency = 0
    cost: float | None = 0.0
    error = None
    raw = None
    res: dict[str, Any] = {}
    for attempt in (1, 2):
        res = provider.complete(task, system, messages, schema, model=model)
        tot_in += res.get("input_tokens") or 0
        tot_out += res.get("output_tokens") or 0
        latency += res.get("latency_ms") or 0
        c = res.get("cost_usd")
        cost = None if (c is None or cost is None) else cost + c
        raw = res.get("raw")
        try:
            if res.get("output") is None:
                raise ValueError("reply was not valid JSON")
            value = model_cls.model_validate(res["output"])
            return StructuredResult(True, value, None, res["provider"], res["model"], tot_in, tot_out, cost,
                                    latency, attempt, raw)
        except (ValidationError, ValueError) as exc:
            error = str(exc)[:600]
            messages = messages + [
                {"role": "assistant", "content": raw or ""},
                {"role": "user", "content": "Your reply was invalid: " + error +
                 "\nReply again with only a JSON object that fixes this."}]
    return StructuredResult(False, None, error, res.get("provider", provider.name), res.get("model", model or ""),
                            tot_in, tot_out, cost, latency, 2, raw)
