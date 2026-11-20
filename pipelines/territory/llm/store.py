"""ai_outputs / ai_task_runs access: append-only writes, cache lookup, monthly spend (budget guard)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb


def input_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def month_spend(conn, client_id: str) -> tuple[float, int]:
    """(USD spent this calendar month across all tasks, number of outputs whose cost is unknown)."""
    row = conn.execute(
        "select coalesce(sum(cost_usd), 0), count(*) filter (where cost_usd is null) from ai_outputs "
        "where client_id = %s and created_at >= date_trunc('month', now())", (client_id,)).fetchone()
    return float(row[0]), int(row[1])


def find_cached(conn, client_id: str, task: str, subject_id: str, ihash: str, prompt_version: str) -> str | None:
    r = conn.execute(
        "select id from ai_outputs where client_id=%s and task=%s and subject_id=%s and input_hash=%s "
        "and prompt_version=%s and status='valid' limit 1", (client_id, task, subject_id, ihash, prompt_version)).fetchone()
    return str(r[0]) if r else None


def cached_hashes(conn, client_id: str, task: str, prompt_version: str, subject_ids: list[str]) -> dict[str, set[str]]:
    """subject_id -> input hashes that already have a valid row (bulk lookup for permit_intent)."""
    out: dict[str, set[str]] = {}
    for sid, h in conn.execute(
            "select subject_id, input_hash from ai_outputs where client_id=%s and task=%s and prompt_version=%s "
            "and status='valid' and subject_id = any(%s)", (client_id, task, prompt_version, subject_ids)):
        out.setdefault(sid, set()).add(h)
    return out


@dataclass
class OutputRow:
    client_id: str
    task: str
    subject_type: str
    subject_id: str
    input_hash: str
    prompt_version: str
    provider: str
    model: str
    status: str                              # valid | invalid | rejected
    output: Any = None
    cited_record_ids: list[str] = field(default_factory=list)
    uses_sample: bool = False
    rejection_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    attempt: int = 1                         # 1 = primary, 2 = retry with the reason appended, 3 = fallback model
    is_fallback: bool = False


INSERT_OUTPUT = (
    "insert into ai_outputs (client_id, task, subject_type, subject_id, input_hash, prompt_version, provider, model, "
    "output, cited_record_ids, uses_sample, status, rejection_reason, input_tokens, output_tokens, cost_usd, "
    "attempt, is_fallback) "
    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")


def insert_outputs(conn, rows: list[OutputRow]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(INSERT_OUTPUT, [
            (r.client_id, r.task, r.subject_type, r.subject_id, r.input_hash, r.prompt_version, r.provider, r.model,
             Jsonb(r.output) if r.output is not None else None, r.cited_record_ids, r.uses_sample, r.status,
             r.rejection_reason, r.input_tokens, r.output_tokens, r.cost_usd, r.attempt, r.is_fallback) for r in rows])


@dataclass
class TaskStats:
    task: str
    model: str | None = None
    status: str = "success"                  # success | skipped | budget_stopped | failed
    skip_reason: str | None = None
    calls: int = 0
    cached: int = 0
    valid: int = 0
    invalid: int = 0
    rejected: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_unknown: bool = False
    retried: int = 0                         # subjects that needed more than one call
    fallbacks: int = 0                       # subjects that reached the fallback model
    warnings: list[str] = field(default_factory=list)

    def add_cost(self, c: float | None) -> None:
        if c is None:
            self.cost_unknown = True
        else:
            self.cost_usd += c


def record_task_run(conn, client_id: str, s: TaskStats, started_at=None) -> None:
    conn.execute(
        "insert into ai_task_runs (client_id, task, started_at, finished_at, status, skip_reason, calls, cached, valid, "
        "invalid, rejected, input_tokens, output_tokens, cost_usd, cost_unknown, warnings, model, retried, fallbacks) "
        "values (%s,%s,coalesce(%s, now()),now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (client_id, s.task, started_at, s.status, s.skip_reason, s.calls, s.cached, s.valid, s.invalid, s.rejected,
         s.input_tokens, s.output_tokens, round(s.cost_usd, 6), s.cost_unknown, s.warnings, s.model, s.retried,
         s.fallbacks))


class BudgetGuard:
    """Before each call: stop the task if this month's spend plus the expected cost of the call would exceed the budget.
    Expected cost = the average cost per call so far in this run (0 before the first call)."""

    def __init__(self, conn, client_id: str, budget_usd: float, stats: TaskStats):
        self.conn, self.client_id, self.budget, self.stats = conn, client_id, budget_usd, stats
        self.spent, _ = month_spend(conn, client_id)
        self.start_spent = self.spent

    def allow(self) -> bool:
        avg = (self.stats.cost_usd / self.stats.calls) if self.stats.calls else 0.0
        if self.start_spent + self.stats.cost_usd + avg > self.budget:
            if self.stats.status != "budget_stopped":
                self.stats.status = "budget_stopped"
                self.stats.warnings.append(
                    f"{self.stats.task}: stopped, the monthly AI budget of ${self.budget:.2f} would be exceeded "
                    f"(${self.start_spent + self.stats.cost_usd:.2f} spent this month)")
            return False
        return True
