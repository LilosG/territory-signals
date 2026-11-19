"""Run bookkeeping: every run writes a source_runs row; work is all-or-nothing."""
from __future__ import annotations

import traceback
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from psycopg.types.json import Jsonb

from territory.db import connect, refresh_dashboard_aggregates
from territory.reports import write_match_report
from territory.sources.base import (
    AwaitingManualDownload, RunContext, SignalCandidate, SourceAdapter,
)

AWAITING_MESSAGE = "awaiting manual download"
BATCH = 2000


def clean_json(obj: Any) -> Any:
    """Make a value safe for jsonb: NaN/inf become null (JSON has no NaN)."""
    if isinstance(obj, float):
        return obj if obj == obj and obj not in (float("inf"), float("-inf")) else None
    if isinstance(obj, dict):
        return {k: clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    return obj


@dataclass
class WorkResult:
    rows_fetched: int = 0
    rows_matched: int = 0
    rows_unmatched: int = 0
    signals_written: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunOutcome:
    source_key: str
    run_id: str
    status: str
    rows_fetched: int = 0
    rows_matched: int = 0
    rows_unmatched: int = 0
    signals_written: int = 0
    error: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


def tracked_run(source_key: str, work: Callable[[Any, str], WorkResult]) -> RunOutcome:
    """Open a source_runs row, run `work(conn, run_id)` in ONE transaction, then
    mark success (commit) or failed (rollback + error). Never leaves a half-written run."""
    with connect(autocommit=True) as ctl:
        run_id = str(ctl.execute(
            "insert into source_runs (source_key, status) values (%s, 'running') returning id",
            (source_key,)).fetchone()[0])
    work_conn = connect()
    try:
        result = work(work_conn, run_id)
        work_conn.execute(
            "update source_runs set status='success', finished_at=now(), rows_fetched=%s, "
            "rows_matched=%s, rows_unmatched=%s where id=%s",
            (result.rows_fetched, result.rows_matched, result.rows_unmatched, run_id))
        work_conn.commit()
        refresh_dashboard_aggregates()   # /trends reads pre-computed tables
        return RunOutcome(source_key, run_id, "success", result.rows_fetched,
                          result.rows_matched, result.rows_unmatched,
                          result.signals_written, None, result.extra)
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded
        work_conn.rollback()
        if isinstance(exc, AwaitingManualDownload):
            message = AWAITING_MESSAGE
        else:
            message = f"{type(exc).__name__}: {exc}"[:2000]
            traceback.print_exc()
        with connect(autocommit=True) as ctl:
            ctl.execute(
                "update source_runs set status='failed', finished_at=now(), error_message=%s "
                "where id=%s", (message, run_id))
        return RunOutcome(source_key, run_id, "failed", error=message)
    finally:
        work_conn.close()


def _insert_signal(conn, run_id: str, c: SignalCandidate) -> int:
    for name in ("source_key", "source_record_id", "match_method"):
        if not getattr(c, name):
            raise ValueError(f"signal {c.signal_type} is missing {name}")
    if c.confidence is None or not 0 <= c.confidence <= 1:
        raise ValueError(f"signal {c.signal_type} has invalid confidence {c.confidence!r}")
    if c.apn is None:
        raise ValueError(f"signal {c.signal_type}/{c.source_record_id} has no apn")
    cur = conn.execute(
        "insert into signals (apn, signal_type, signal_group, signal_date, source_key, "
        "source_record_id, run_id, confidence, match_method, is_estimate, is_sample, details) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "on conflict on constraint signals_natural_key do nothing",
        (c.apn, c.signal_type, c.signal_group, c.signal_date, c.source_key,
         c.source_record_id, run_id, c.confidence, c.match_method, c.is_estimate,
         c.is_sample, Jsonb(clean_json(c.details))))
    return cur.rowcount


def _flush_raw(conn, run_id: str, fetched_at: datetime, rows: list) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into raw_records (source_key, source_record_id, run_id, payload, fetched_at) "
            "values (%s,%s,%s,%s,%s)",
            [(r.source_key, r.source_record_id, run_id, Jsonb(clean_json(r.payload)), fetched_at) for r in rows])
    rows.clear()


def run_adapter(adapter_cls: type[SourceAdapter], ctx_factory: Callable[[Any, str], RunContext],
                report_dir: Path | None = None) -> RunOutcome:
    key = adapter_cls.source_key

    def work(conn, run_id: str) -> WorkResult:
        ctx = ctx_factory(conn, run_id)
        adapter = adapter_cls(ctx)
        adapter.prepare()
        fetched_at = datetime.now(timezone.utc)
        res = WorkResult()
        methods: Counter = Counter()
        examples: list[dict] = []
        pending: list = []
        for raw in adapter.fetch(run_id):
            res.rows_fetched += 1
            pending.append(raw)
            m = adapter.match(raw)
            if m.apn:
                res.rows_matched += 1
                methods[m.method] += 1
            else:
                res.rows_unmatched += 1
                if len(examples) < 10:
                    examples.append(adapter.safe_view(raw))
            for cand in adapter.normalize(raw):
                res.signals_written += _insert_signal(conn, run_id, cand)
            if len(pending) >= BATCH:
                _flush_raw(conn, run_id, fetched_at, pending)
        _flush_raw(conn, run_id, fetched_at, pending)
        for cand in adapter.finalize():
            res.signals_written += _insert_signal(conn, run_id, cand)
        res.extra = dict(adapter.notes)
        write_match_report(key, fetched=res.rows_fetched, matched=res.rows_matched,
                           unmatched=res.rows_unmatched, methods=methods, examples=examples,
                           notes=adapter.notes, signals_written=res.signals_written,
                           report_dir=report_dir or ctx.report_dir)
        return res

    return tracked_run(key, work)
