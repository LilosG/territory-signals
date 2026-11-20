"""Retry and fallback for every AI task (Phase 5G).

One subject (a parcel, a week) goes through a chain of at most three calls:

  1. primary   the task's model.
  2. retry     the same model, with the rejection reason appended to the conversation.
  3. fallback  `llm.tasks.<task>.fallback_model`, fresh, only if the retry also failed.

A reply is *valid* when it parses, matches the schema, is not empty and passes the task's deterministic validator.
An empty reply counts as rejected. A provider error (after the adapter's own HTTP retries) skips the retry, since
there is no reply to correct, and goes straight to the fallback.

Every attempt is stored (ai_outputs, with its attempt number and a fallback flag). Readers show only the latest
*valid* row, so a rejected first attempt is never shown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from territory.llm import store
from territory.llm.base import LLMError, Provider, schema_of
from territory.llm.validators import strings_of

PRIMARY, RETRY, FALLBACK = "primary", "retry", "fallback"


@dataclass
class Evaluation:
    """The task's deterministic verdict on a schema-valid reply. `output` is what gets stored when there are no problems."""
    output: Any = None
    problems: list[str] = field(default_factory=list)
    cited: list[str] = field(default_factory=list)
    uses_sample: bool = False


Evaluate = Callable[[Any], Evaluation]


@dataclass
class Attempt:
    n: int
    role: str                          # primary | retry | fallback
    model: str
    provider: str
    status: str                        # valid | invalid | rejected
    output: Any = None
    problems: list[str] = field(default_factory=list)
    cited: list[str] = field(default_factory=list)
    uses_sample: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0       # None = unknown
    latency_ms: int = 0
    raw: str | None = None
    provider_error: bool = False
    value: BaseModel | None = None

    @property
    def reason(self) -> str | None:
        return "; ".join(self.problems)[:500] or None


def feedback(status: str, problems: list[str]) -> str:
    why = "; ".join(problems)[:600] or "no reason given"
    kind = "rejected" if status == "rejected" else "invalid"
    return f"Your reply was {kind}: {why}\nReply again with only a JSON object that fixes this."


def is_blank(value: BaseModel) -> bool:
    """True when every text in the reply is empty (an empty object or all-blank fields)."""
    return not any(s.strip() for s in strings_of(value.model_dump()))


def one_call(provider: Provider, task: str, system: str, messages: list[dict], model_cls: type[BaseModel],
             model: str | None, evaluate: Evaluate, n: int, role: str) -> Attempt:
    try:
        res = provider.complete(task, system, messages, schema_of(model_cls), model=model)
    except LLMError as exc:
        return Attempt(n, role, model or "", getattr(provider, "name", ""), "invalid",
                       problems=[f"provider error: {str(exc)[:300]}"], provider_error=True)
    base = dict(n=n, role=role, model=res.get("model") or model or "", provider=res.get("provider") or "",
                input_tokens=res.get("input_tokens") or 0, output_tokens=res.get("output_tokens") or 0,
                cost_usd=res.get("cost_usd"), latency_ms=res.get("latency_ms") or 0, raw=res.get("raw"))
    if not (res.get("raw") or "").strip():
        return Attempt(**base, status="rejected", problems=["empty output"])
    if res.get("output") is None:
        return Attempt(**base, status="invalid", problems=["reply was not valid JSON"])
    try:
        value = model_cls.model_validate(res["output"])
    except ValidationError as exc:
        return Attempt(**base, status="invalid", problems=[str(exc)[:600]])
    if is_blank(value):
        return Attempt(**base, status="rejected", problems=["empty output"], value=value)
    ev = evaluate(value)
    if ev.problems:
        return Attempt(**base, status="rejected", problems=ev.problems, value=value)
    return Attempt(**base, status="valid", output=ev.output, cited=ev.cited, uses_sample=ev.uses_sample, value=value)


def retry_messages(user: str, failed: Attempt) -> list[dict]:
    note = feedback(failed.status, failed.problems)
    if (failed.raw or "").strip():
        return [{"role": "user", "content": user}, {"role": "assistant", "content": failed.raw}, {"role": "user", "content": note}]
    return [{"role": "user", "content": user + "\n\n" + note}]     # nothing to echo back for an empty reply


def run_chain(provider: Provider, task: str, system: str, user: str, model_cls: type[BaseModel], evaluate: Evaluate,
              model: str | None, fallback_model: str | None = None) -> list[Attempt]:
    """The attempts for one subject, in order. The last one is the outcome; it is valid or everything failed."""
    first = one_call(provider, task, system, [{"role": "user", "content": user}], model_cls, model, evaluate, 1, PRIMARY)
    attempts = [first]
    if first.status == "valid":
        return attempts
    if not first.provider_error:
        second = one_call(provider, task, system, retry_messages(user, first), model_cls, model, evaluate, 2, RETRY)
        attempts.append(second)
        if second.status == "valid":
            return attempts
    if fallback_model and fallback_model != model:
        attempts.append(one_call(provider, task, system, [{"role": "user", "content": user}], model_cls, fallback_model,
                                 evaluate, len(attempts) + 1, FALLBACK))
    return attempts


def totals(attempts: list[Attempt]) -> tuple[int, int, float | None]:
    cost: float | None = 0.0
    for a in attempts:
        cost = None if (a.cost_usd is None or cost is None) else cost + a.cost_usd
    return sum(a.input_tokens for a in attempts), sum(a.output_tokens for a in attempts), cost


def record(stats: store.TaskStats, attempts: list[Attempt], what: str = "one subject") -> Attempt:
    """Add a chain's calls, tokens, cost and final outcome to the task stats. Returns the final attempt."""
    final = attempts[-1]
    stats.calls += len(attempts)
    for a in attempts:
        stats.input_tokens += a.input_tokens
        stats.output_tokens += a.output_tokens
        stats.add_cost(a.cost_usd)
    setattr(stats, final.status, getattr(stats, final.status) + 1)
    if len(attempts) > 1:
        stats.retried += 1
    if any(a.role == FALLBACK for a in attempts):
        stats.fallbacks += 1
    if final.provider_error:
        stats.status = "failed" if stats.status == "success" else stats.status
        stats.warnings.append(f"{stats.task}: provider error for {what}: {final.reason}")
    return final


def rows(attempts: list[Attempt], client_id: str, task: str, subject_type: str, subject_id: str, ihash: str,
         prompt_version: str) -> list[store.OutputRow]:
    """One ai_outputs row per attempt (append-only). The latest valid one is the only one readers show."""
    return [store.OutputRow(
        client_id, task, subject_type, subject_id, ihash, prompt_version, a.provider, a.model, a.status,
        output=a.output if a.status == "valid" else None, cited_record_ids=a.cited if a.status == "valid" else [],
        uses_sample=a.uses_sample if a.status == "valid" else False, rejection_reason=a.reason,
        input_tokens=a.input_tokens, output_tokens=a.output_tokens, cost_usd=a.cost_usd,
        attempt=a.n, is_fallback=a.role == FALLBACK) for a in attempts]
