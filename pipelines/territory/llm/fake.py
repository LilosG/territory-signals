"""Deterministic provider for tests. No network. A handler maps (task, system, messages) to a reply."""
from __future__ import annotations

import json
from typing import Any, Callable

Handler = Callable[[str, str, list[dict]], Any]


class FakeProvider:
    name = "fake"

    def __init__(self, handler: Handler | None = None, replies: list[Any] | None = None, model: str = "fake-model",
                 cost_per_call: float = 0.001):
        self.handler = handler
        self.replies = list(replies or [])
        self.model = model
        self.cost = cost_per_call
        self.calls: list[dict] = []

    def complete(self, task: str, system: str, messages: list[dict], json_schema: dict | None,
                 model: str | None = None) -> dict[str, Any]:
        self.calls.append({"task": task, "system": system, "messages": messages, "model": model})
        reply = self.replies.pop(0) if self.replies else (self.handler(task, system, messages) if self.handler else {})
        raw = reply if isinstance(reply, str) else json.dumps(reply)
        try:
            out = json.loads(raw)
        except ValueError:
            out = None
        n_in = sum(len(m["content"]) for m in messages) // 4 + len(system) // 4
        return {"output": out, "raw": raw, "provider": self.name, "model": model or self.model,
                "input_tokens": n_in, "output_tokens": len(raw) // 4, "cost_usd": self.cost, "latency_ms": 1}
