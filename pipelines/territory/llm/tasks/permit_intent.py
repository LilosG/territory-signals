"""permit_intent (shadow mode): classify a permit's free-text description. Never changes scores or recipes."""
from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from territory.config import ClientConfig
from territory.llm import attempts as at, store
from territory.llm.base import LLMError, Provider, schema_of
from territory.llm.prompts import load_prompt
from territory.llm.validators import quote_in_source

TASK = "permit_intent"
BATCH = 8                  # reasoning models take 10-90 s for 15 permits; smaller batches stay under the 60 s timeout
MAX_DESC = 600
Intent = Literal["prep_to_sell", "long_term_stay", "investment_or_redevelopment", "maintenance", "unclear"]
INTENTS = ["prep_to_sell", "long_term_stay", "investment_or_redevelopment", "maintenance", "unclear"]
TAGS = ["kitchen", "bath", "roof", "paint", "flooring", "addition", "adu", "solar", "demolition", "electrical",
        "plumbing", "hvac", "windows_doors", "deck_patio", "pool", "fence_wall", "foundation_structural", "garage",
        "landscape", "commercial", "signage", "other"]


class PermitItem(BaseModel):
    id: int
    intent: Intent
    scope_tags: list[str]
    confidence: float = Field(ge=0, le=1)
    quote: str
    reason: str


class PermitBatch(BaseModel):
    items: list[PermitItem]


@dataclass
class Permit:
    record_id: str          # the City approval id (signals.source_record_id)
    description: str
    permit_type: str


def validate_item(item: PermitItem, description: str) -> tuple[dict | None, str | None]:
    """Deterministic checks: intent in the enum (pydantic did that), quoted words appear in the description (max 12)."""
    problem = quote_in_source(item.quote, description)
    if problem:
        return None, problem
    if len(item.reason) > 300 or "\n" in item.reason.strip():
        return None, "reason is not one short line"
    tags = [t for t in dict.fromkeys(item.scope_tags) if t in TAGS]
    return {"intent": item.intent, "scope_tags": tags, "confidence": item.confidence,
            "quote": item.quote.strip(), "reason": item.reason.strip()}, None


def load_permits(conn, limit: int | None = None, scope=None, today=None) -> list[Permit]:
    """Distinct live permit approvals with a free-text description (scope, else job description).
    `scope` (llm.tasks.permit_intent.scope): only permits issued in the last `months` months OR on a parcel whose
    latest score is at least `min_lead_score`. None = every permit."""
    from datetime import date
    from dateutil.relativedelta import relativedelta
    where, params = "", []
    if scope is not None:
        where = " and (signal_date >= %s or apn in (select apn from latest_scores where score >= %s))"
        params = [(today or date.today()) - relativedelta(months=scope.months), scope.min_lead_score]
    from territory.scoring_engine import load_permit_labels
    labels = load_permit_labels()
    rows = conn.execute(
        f"""select distinct on (source_record_id) source_record_id,
                  coalesce(nullif(btrim(details->>'scope'), ''), nullif(btrim(details->>'job_description'), '')) as d,
                  details->>'approval_type'
             from signals where signal_type = 'permit_approved' and superseded_by is null
              and length(coalesce(nullif(btrim(details->>'scope'), ''), nullif(btrim(details->>'job_description'), ''), '')) >= 10
              {where}
            order by source_record_id, signal_date desc nulls last""", params).fetchall()
    out = [Permit(r, d[:MAX_DESC], labels.get(t) or labels.get(t or "") or (t or "")) for r, d, t in rows]
    return out[:limit] if limit else out


def permit_hash(p: Permit) -> str:
    return store.input_hash({"d": p.description, "t": p.permit_type})


@dataclass
class Call:
    """One provider call covering several permits."""
    n: int
    role: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0
    permits: int = 1                  # how many permits this call covered (cost and tokens are shared between them)


@dataclass
class PermitAttempt:
    call: Call
    status: str                       # valid | invalid | rejected
    output: dict | None
    reason: str | None
    provider_error: bool = False


@dataclass
class BatchResult:
    calls: list[Call]
    per_permit: list[list[PermitAttempt]]      # attempts for each permit, in order

    @property
    def final(self) -> list[PermitAttempt]:
        return [a[-1] for a in self.per_permit]


def _request(permits: list[Permit], ids: list[int]) -> str:
    return json.dumps([{"id": i + 1, "permit_type": permits[i].permit_type, "description": permits[i].description}
                       for i in ids], ensure_ascii=False)


def _ask(provider: Provider, system: str, messages: list[dict], model: str | None, n: int, role: str,
         permits: list[Permit], ids: list[int], remap: dict[int, int] | None = None):
    """One call. Returns (Call, {permit index: PermitAttempt}, raw reply). `remap` maps the ids the model saw to
    permit indexes (the fallback call renumbers the permits it is given)."""
    call = Call(n, role, model or "", getattr(provider, "name", ""), permits=len(ids))
    out: dict[int, PermitAttempt] = {}
    remap = remap or {i + 1: i for i in ids}

    def fail(status: str, why: str, provider_error: bool = False):
        for i in ids:
            out[i] = PermitAttempt(call, status, None, why, provider_error)
        return call, out, None

    try:
        res = provider.complete(TASK, system, messages, schema_of(PermitBatch), model=model)
    except LLMError as exc:
        return fail("invalid", f"provider error: {str(exc)[:300]}", True)
    call.model, call.provider = res.get("model") or call.model, res.get("provider") or call.provider
    call.input_tokens, call.output_tokens, call.cost_usd = res.get("input_tokens") or 0, res.get("output_tokens") or 0, res.get("cost_usd")
    raw = res.get("raw")
    if not (raw or "").strip():
        return call, {i: PermitAttempt(call, "rejected", None, "empty output") for i in ids}, raw
    try:
        if res.get("output") is None:
            raise ValueError("reply was not valid JSON")
        value = PermitBatch.model_validate(res["output"])
    except (ValidationError, ValueError) as exc:
        return call, {i: PermitAttempt(call, "invalid", None, str(exc)[:600]) for i in ids}, raw
    by_id = {remap[it.id]: it for it in value.items if it.id in remap}
    for i in ids:
        it = by_id.get(i)
        if it is None:
            out[i] = PermitAttempt(call, "invalid", None, "missing from the reply")
            continue
        stored, problem = validate_item(it, permits[i].description)
        out[i] = PermitAttempt(call, "valid", stored, None) if stored else PermitAttempt(
            call, "rejected", {"intent": it.intent, "quote": it.quote}, problem)
    return call, out, raw


def classify_batch(provider: Provider, system: str, permits: list[Permit], model: str | None,
                   fallback_model: str | None = None) -> BatchResult:
    """One call for several permits, then Phase 5G retry + fallback for the permits that failed:
    retry the same model once for only those permits with the reasons appended, then ask the fallback model
    (fresh) for those still failing. Valid permits are never asked again."""
    calls: list[Call] = []
    per: list[list[PermitAttempt]] = [[] for _ in permits]
    everyone = list(range(len(permits)))
    user = _request(permits, everyone)
    call, out, raw = _ask(provider, system, [{"role": "user", "content": user}], model, 1, at.PRIMARY, permits, everyone)
    calls.append(call)
    for i, a in out.items():
        per[i].append(a)
    failed = [i for i in everyone if per[i][-1].status != "valid"]
    if failed and not all(per[i][-1].provider_error for i in failed):
        reasons = "\n".join(f"- id {i + 1}: {per[i][-1].reason}" for i in failed)
        note = (f"These items were rejected:\n{reasons}\nReply again with only a JSON object containing items for "
                f"id {', '.join(str(i + 1) for i in failed)}, fixed (keep the same ids).")
        if raw and raw.strip():
            msgs = [{"role": "user", "content": user}, {"role": "assistant", "content": raw}, {"role": "user", "content": note}]
        else:
            msgs = [{"role": "user", "content": user + "\n\n" + note}]
        call, out, _ = _ask(provider, system, msgs, model, 2, at.RETRY, permits, failed)
        calls.append(call)
        for i, a in out.items():
            per[i].append(a)
        failed = [i for i in failed if per[i][-1].status != "valid"]
    if failed and fallback_model and fallback_model != model:
        sub = [permits[i] for i in failed]                                # renumbered 1..k for the fallback model
        call, out, _ = _ask(provider, system, [{"role": "user", "content": _request(sub, list(range(len(sub))))}],
                            fallback_model, 3, at.FALLBACK, sub, list(range(len(sub))))
        calls.append(call)
        for k, a in out.items():
            per[failed[k]].append(a)
    return BatchResult(calls, per)


def run(conn, client: ClientConfig, provider: Provider, stats: store.TaskStats, limit: int | None = None,
        workers: int = 32, batch_size: int = BATCH) -> None:
    system, version = load_prompt(TASK)
    model = client.llm.model_for(TASK)
    fallback = client.llm.fallback_model_for(TASK)
    stats.model = model
    task_cfg = client.llm.tasks.get(TASK)
    permits = load_permits(conn, limit, scope=task_cfg.scope if task_cfg else None)
    done = store.cached_hashes(conn, client.client_id, TASK, version, [p.record_id for p in permits])
    todo = [p for p in permits if permit_hash(p) not in done.get(p.record_id, set())]
    stats.cached = len(permits) - len(todo)
    guard = store.BudgetGuard(conn, client.client_id, client.llm.monthly_budget_usd, stats)
    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]

    def work(b: list[Permit]):
        try:
            return b, classify_batch(provider, system, b, model, fallback), None
        except LLMError as exc:
            return b, None, exc

    pending = set()
    it = iter(batches)

    def submit(ex):
        if not guard.allow():
            return False
        b = next(it, None)
        if b is None:
            return False
        pending.add(ex.submit(work, b))
        return True

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in range(workers):
            if not submit(ex):
                break
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for f in finished:
                pending.discard(f)
                b, res, err = f.result()
                if res is None:                                   # the batch call itself failed: nothing stored
                    stats.calls += 1
                    stats.warnings.append(f"{TASK}: provider error: {err}")
                    stats.status = "failed" if stats.status == "success" else stats.status
                    submit(ex)
                    continue
                stats.calls += len(res.calls)
                for c in res.calls:
                    stats.input_tokens += c.input_tokens
                    stats.output_tokens += c.output_tokens
                    stats.add_cost(c.cost_usd)
                rows = []
                for p, attempts in zip(b, res.per_permit):
                    final = attempts[-1]
                    if final.provider_error and stats.status == "success":
                        stats.status = "failed"
                        stats.warnings.append(f"{TASK}: provider error: {final.reason}")
                    setattr(stats, final.status, getattr(stats, final.status) + 1)
                    stats.retried += len(attempts) > 1
                    stats.fallbacks += any(a.call.role == at.FALLBACK for a in attempts)
                    for a in attempts:
                        n = max(a.call.permits, 1)
                        rows.append(store.OutputRow(
                            client.client_id, TASK, "permit", p.record_id, permit_hash(p), version, a.call.provider,
                            a.call.model, a.status, output=a.output if a.status != "invalid" else None,
                            cited_record_ids=[p.record_id] if a.status == "valid" else [], rejection_reason=a.reason,
                            input_tokens=a.call.input_tokens // n, output_tokens=a.call.output_tokens // n,
                            cost_usd=None if a.call.cost_usd is None else round(a.call.cost_usd / n, 6),
                            attempt=a.call.n, is_fallback=a.call.role == at.FALLBACK))
                store.insert_outputs(conn, rows)
                submit(ex)
