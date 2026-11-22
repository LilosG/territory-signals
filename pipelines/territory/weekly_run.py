"""End-to-end weekly orchestrator: python -m territory.weekly_run --client kaiser-team [--cloud] [--skip-ai] [--send-digest]

Runs the weekly pipeline in a fixed order and logs each stage's duration, row counts and status:

  1. live sources: stro_licenses, dev_permits, code_enforcement, tax_default, upzoning_estimate, then fire_zones
     (fire_zones only waits for Mike's manual file; that state never aborts the batch)
  2. permit_rederive
  3. portfolio (deterministic entity / mailing-address clustering over the current owners snapshot)
  4. score
  5. refresh the dashboard SQL aggregates (private.refresh_dashboard_aggregates)
  6. AI (unless --skip-ai): lead_brief (cached, so only new/changed leads cost anything, within the client's
     monthly budget) and weekly_brief
  7. Monday Executive Digest HTML + text; write data/outbox/latest_digest.html, or send it with --send-digest

The cloud guard is preserved: every connection refuses a non-local host unless --cloud is passed.
Local runs reuse the newest on-disk download under data/raw/<source>/ when one exists, so a dry run is repeatable
and offline; --cloud always fetches live.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from territory import db, digest
from territory.config import ClientConfig, load_client
from territory.db import connect, db_host, refresh_dashboard_aggregates, LOCAL_HOSTS
from territory.net import DATA_DIR
from territory.permit_rederive import SOURCE_KEY as PERMIT_REDERIVE_KEY, rederive, write_report as write_permit_report
from territory.portfolio import recompute_portfolios
from territory.run import run_one
from territory.runner import AWAITING_MESSAGE, WorkResult, tracked_run
from territory.score import run_score
from territory.scoring_engine import load_scoring_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"

LIVE_SOURCES = ["stro_licenses", "dev_permits", "code_enforcement", "tax_default", "upzoning_estimate", "fire_zones"]
AI_TASKS = ["lead_brief", "weekly_brief"]


@dataclass
class Stage:
    name: str
    status: str                 # success | skipped | awaiting | failed
    seconds: float
    rows: int = 0
    detail: str = ""

    def line(self) -> str:
        return f"  {self.name:18s} {self.status:8s} {self.seconds:7.2f}s rows={self.rows:<8d} {self.detail}".rstrip()


@dataclass
class WeeklyResult:
    stages: list[Stage] = field(default_factory=list)
    digest_path: Path | None = None
    digest_text_path: Path | None = None
    sent_to: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(s.status == "failed" for s in self.stages)


# ---------------------------------------------------------------------------------------
# local download cache
# ---------------------------------------------------------------------------------------
def _newest_raw_dir(source_key: str, run_date: date) -> Path | None:
    base = DATA_DIR / "raw" / source_key
    if not base.exists():
        return None
    dirs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda p: p.name)
    if not dirs:
        return None
    for d in reversed(dirs):
        if d.name == run_date.isoformat():
            return d
    return dirs[-1]


def cached_local_files(source_key: str, run_date: date) -> dict[str, Any]:
    """The newest cached download for a source, mapped to the keys its adapter accepts. Empty when nothing is cached."""
    d = _newest_raw_dir(source_key, run_date)
    if d is None:
        return {}
    files = [f for f in sorted(d.iterdir()) if f.is_file()]
    if source_key == "dev_permits":
        permits = [f for f in files if f.name.startswith("approvals_") and f.suffix.lower() == ".csv"]
        if not permits:
            return {}
        return {"dev_permits": permits, "permit_signal_map": CONFIG_DIR / "permit_signal_map.yaml"}
    if source_key == "code_enforcement":
        f = next((f for f in files if f.suffix.lower() == ".csv"), None)
        return {"code_enforcement": f} if f else {}
    if source_key == "stro_licenses":
        f = next((f for f in files if f.suffix.lower() == ".csv"), None)
        return {"stro_licenses": f} if f else {}
    if source_key == "tax_default":
        f = next((f for f in files if f.suffix.lower() == ".pdf"), None)
        return {"tax_default": f} if f else {}
    if source_key == "upzoning_estimate":
        stops = next((f for f in files if "Transit_Stops" in f.name), None)
        routes = next((f for f in files if "Transit_Routes" in f.name), None)
        return {"transit_stops": stops, "transit_routes": routes} if stops and routes else {}
    return {}


# ---------------------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------------------
def _ingest_source(client: ClientConfig, key: str, run_date: date, local_files: Mapping[str, Any] | None,
                   report_dir: Path | None, use_cached: bool) -> Stage:
    started = time.perf_counter()
    files = dict(local_files) if local_files is not None else (cached_local_files(key, run_date) if use_cached else {})
    kwargs: dict[str, Any] = {"report_dir": report_dir} if report_dir is not None else {}
    if files:
        kwargs["local_files"] = files
    try:
        o = run_one(client, key, run_date=run_date, **kwargs)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - one source failing must not stop the weekly batch
        return Stage(key, "failed", time.perf_counter() - started, 0, f"{type(exc).__name__}: {exc}")
    seconds = time.perf_counter() - started
    if o.status == "failed" and o.error == AWAITING_MESSAGE:
        return Stage(key, "awaiting", seconds, o.rows_fetched, "awaiting manual download")
    if o.status == "failed":
        return Stage(key, "failed", seconds, o.rows_fetched, o.error or "failed")
    return Stage(key, "success", seconds, o.rows_fetched,
                 f"matched={o.rows_matched} signals={o.signals_written}")


def _permit_rederive_stage(run_date: date, report_dir: Path | None) -> Stage:
    started = time.perf_counter()
    out: dict[str, Any] = {}

    def work(conn, run_id: str) -> WorkResult:
        out.update(rederive(conn, run_id, run_date))
        return WorkResult(rows_fetched=out["approvals_checked"], signals_written=out["inserted"])

    try:
        o = tracked_run(PERMIT_REDERIVE_KEY, work)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        return Stage("permit_rederive", "failed", time.perf_counter() - started, 0, f"{type(exc).__name__}: {exc}")
    seconds = time.perf_counter() - started
    if o.status != "success":
        return Stage("permit_rederive", "failed", seconds, o.rows_fetched or 0, o.error or "failed")
    try:
        write_permit_report(out, run_date, report_dir=report_dir)
    except OSError:
        pass
    return Stage("permit_rederive", "success", seconds, o.rows_fetched,
                 f"superseded={out.get('superseded', 0)} inserted={out.get('inserted', 0)}")


def _portfolio_stage() -> Stage:
    started = time.perf_counter()
    try:
        with connect() as conn:
            summary = recompute_portfolios(conn)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        return Stage("portfolio", "failed", time.perf_counter() - started, 0, f"{type(exc).__name__}: {exc}")
    return Stage("portfolio", "success", time.perf_counter() - started, int(summary["parcels"]),
                 f"portfolios={summary['portfolios']} multi_parcels={summary['multi_parcel_parcels']}")


def _score_stage(run_date: date, report_dir: Path | None) -> Stage:
    started = time.perf_counter()
    try:
        cfg = load_scoring_config()
        with connect() as conn:
            summary = run_score(conn, cfg, run_date, report_dir=report_dir)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        return Stage("score", "failed", time.perf_counter() - started, 0, f"{type(exc).__name__}: {exc}")
    suppressed = sum((summary.get("suppressed") or {}).values())
    return Stage("score", "success", time.perf_counter() - started, int(summary["scored"]),
                 f"model={summary['model_version']} suppressed={suppressed}")


def _refresh_stage() -> Stage:
    started = time.perf_counter()
    ok = refresh_dashboard_aggregates()
    return Stage("refresh_aggregates", "success" if ok else "failed", time.perf_counter() - started,
                 0, "private.refresh_dashboard_aggregates()" + ("" if ok else " failed (see warning)"))


def _ai_stage(client: ClientConfig, run_date: date, provider, out) -> Stage:
    started = time.perf_counter()
    try:
        from territory.llm.runner import run_ai

        with connect(autocommit=True) as conn:
            stats = run_ai(conn, client, tasks=AI_TASKS, provider=provider, today=run_date, out=out)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        return Stage("ai", "failed", time.perf_counter() - started, 0, f"{type(exc).__name__}: {exc}")
    statuses = ", ".join(f"{s.task}={s.status}" for s in stats)
    failed = any(s.status == "failed" for s in stats)
    rows = sum(s.valid + s.cached for s in stats)
    return Stage("ai", "failed" if failed else ("skipped" if all(s.status == "skipped" for s in stats) else "success"),
                 time.perf_counter() - started, rows, statuses)


def _digest_stage(client: ClientConfig, run_date: date, send: bool,
                  outbox_dir: Path | None) -> tuple[Stage, Path | None, list[str]]:
    started = time.perf_counter()
    html_path: Path | None = None
    sent_to: list[str] = []
    try:
        with connect(autocommit=True) as conn:
            data = digest.collect_digest_data(conn, client, today=run_date)
            html_body, text_body = digest.render_digest(data)
            subject = digest.subject_for(data)
            outbox = outbox_dir or (DATA_DIR / "outbox")
            outbox.mkdir(parents=True, exist_ok=True)
            html_path = outbox / "latest_digest.html"
            text_path = outbox / "latest_digest.txt"
            html_path.write_text(html_body, encoding="utf-8")
            text_path.write_text(text_body, encoding="utf-8")
            if send:
                sent_to = digest.send_digest(html_body, text_body, subject, conn=conn, client=client)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        return Stage("digest", "failed", time.perf_counter() - started, 0,
                     f"{type(exc).__name__}: {exc}"), html_path, sent_to
    detail = f"preview={html_path}"
    if send:
        detail += f" sent={len(sent_to)}"
    return Stage("digest", "success", time.perf_counter() - started, len(data["leads"]), detail), html_path, sent_to


# ---------------------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------------------
def run_weekly(client: ClientConfig, run_date: date | None = None, *, skip_ai: bool = False,
               send_digest: bool = False, local_files: Mapping[str, Any] | None = None,
               report_dir: Path | None = None, outbox_dir: Path | None = None,
               provider=None, out=sys.stdout, use_cached_ingest: bool | None = None) -> WeeklyResult:
    """Run every stage once, in order. Individual source failures are recorded and do not stop the rest of the batch;
    the fire_zones 'awaiting manual download' state is not a failure. Returns a result with every stage and the digest path."""
    run_date = run_date or date.today()
    if use_cached_ingest is None:
        try:
            use_cached_ingest = db_host() in LOCAL_HOSTS and not db._CLOUD_OK
        except Exception:  # noqa: BLE001 - an unreadable URL is caught by connect() with the normal guard message
            use_cached_ingest = False

    result = WeeklyResult()
    result.stages.append(Stage("prepare", "success", 0.0, 0,
                               f"client={client.client_id} date={run_date.isoformat()} ai={'skip' if skip_ai else 'on'}"))

    for key in LIVE_SOURCES:
        stage = _ingest_source(client, key, run_date, local_files, report_dir, use_cached_ingest)
        result.stages.append(stage)
        print(stage.line(), file=out)

    stage = _permit_rederive_stage(run_date, report_dir)
    result.stages.append(stage)
    print(stage.line(), file=out)

    stage = _portfolio_stage()
    result.stages.append(stage)
    print(stage.line(), file=out)

    stage = _score_stage(run_date, report_dir)
    result.stages.append(stage)
    print(stage.line(), file=out)

    stage = _refresh_stage()
    result.stages.append(stage)
    print(stage.line(), file=out)

    if skip_ai:
        stage = Stage("ai", "skipped", 0.0, 0, "--skip-ai")
    else:
        stage = _ai_stage(client, run_date, provider, out)
    result.stages.append(stage)
    print(stage.line(), file=out)

    stage, result.digest_path, result.sent_to = _digest_stage(client, run_date, send_digest, outbox_dir)
    result.digest_text_path = (result.digest_path.parent / "latest_digest.txt") if result.digest_path else None
    result.stages.append(stage)
    print(stage.line(), file=out)

    print(f"weekly run {'OK' if result.ok else 'FAILED'}: "
          f"{sum(1 for s in result.stages if s.status == 'success')} success, "
          f"{sum(1 for s in result.stages if s.status == 'awaiting')} awaiting, "
          f"{sum(1 for s in result.stages if s.status == 'skipped')} skipped, "
          f"{sum(1 for s in result.stages if s.status == 'failed')} failed"
          + (f"; digest={result.digest_path}" if result.digest_path else "")
          + (f"; sent to {len(result.sent_to)} internal recipient(s)" if result.sent_to else ""), file=out)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="territory.weekly_run")
    ap.add_argument("--client", required=True)
    ap.add_argument("--cloud", action="store_true",
                    help="required for any database host other than 127.0.0.1/localhost")
    ap.add_argument("--skip-ai", action="store_true", help="do not run lead_brief or weekly_brief")
    ap.add_argument("--send-digest", action="store_true",
                    help="email the digest to DIGEST_TO (internal team members) instead of only writing the preview")
    args = ap.parse_args(argv)
    if args.cloud:
        db.allow_cloud(True)
    # db.py removes --cloud from sys.argv before argparse sees it in a normal CLI run, so _CLOUD_OK is the second signal.
    cloud = args.cloud or db._CLOUD_OK
    client = load_client(args.client)
    result = run_weekly(client, skip_ai=args.skip_ai, send_digest=args.send_digest,
                        use_cached_ingest=not cloud)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
