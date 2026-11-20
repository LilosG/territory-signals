"""permit_intent (shadow mode): classify a permit's free-text description. Never changes scores or recipes."""
from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from territory.config import ClientConfig
from territory.llm import store
from territory.llm.base import LLMError, Provider, structured
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


def classify_batch(provider: Provider, system: str, permits: list[Permit], model: str | None):
    """One call for several permits. Returns (StructuredResult, per-permit outcomes)."""
    user = json.dumps([{"id": i + 1, "permit_type": p.permit_type, "description": p.description}
                       for i, p in enumerate(permits)], ensure_ascii=False)
    res = structured(provider, TASK, system, user, PermitBatch, model=model)
    outcomes: list[tuple[str, dict | None, str | None]] = []     # (status, output, reason) per permit
    if not res.ok:
        return res, [("invalid", None, res.error)] * len(permits)
    by_id = {it.id: it for it in res.value.items}                # type: ignore[union-attr]
    for i, p in enumerate(permits):
        it = by_id.get(i + 1)
        if it is None:
            outcomes.append(("invalid", None, "missing from the reply"))
            continue
        out, problem = validate_item(it, p.description)
        outcomes.append(("valid", out, None) if out else ("rejected", {"intent": it.intent, "quote": it.quote}, problem))
    return res, outcomes


def run(conn, client: ClientConfig, provider: Provider, stats: store.TaskStats, limit: int | None = None,
        workers: int = 32, batch_size: int = BATCH) -> None:
    system, version = load_prompt(TASK)
    model = client.llm.model_for(TASK)
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
            return b, *classify_batch(provider, system, b, model)
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
                b, res, outcomes = f.result()
                stats.calls += 1
                if res is None:                                   # provider failed after retries: nothing stored
                    stats.warnings.append(f"{TASK}: provider error: {outcomes}")
                    stats.status = "failed" if stats.status == "success" else stats.status
                    submit(ex)
                    continue
                stats.input_tokens += res.input_tokens
                stats.output_tokens += res.output_tokens
                stats.add_cost(res.cost_usd)
                share = None if res.cost_usd is None else round(res.cost_usd / len(b), 6)
                rows = []
                for p, (status, out, why) in zip(b, outcomes):
                    setattr(stats, status, getattr(stats, status) + 1)
                    rows.append(store.OutputRow(
                        client.client_id, TASK, "permit", p.record_id, permit_hash(p), version, res.provider, res.model,
                        status, output=out if status != "invalid" else None,
                        cited_record_ids=[p.record_id] if status == "valid" else [], rejection_reason=why,
                        input_tokens=res.input_tokens // len(b), output_tokens=res.output_tokens // len(b),
                        cost_usd=share))
                store.insert_outputs(conn, rows)
                submit(ex)
