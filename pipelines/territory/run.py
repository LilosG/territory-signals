"""CLI: python -m territory.run --client kaiser-team --source <key|all>

Run from the pipelines/ directory (or with PYTHONPATH=pipelines).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from territory.config import load_client
from territory.layers import LAYERS
from territory.runner import AWAITING_MESSAGE, RunOutcome, run_adapter, tracked_run
from territory.registry import ADAPTERS
from territory.sources.base import RunContext

ORDER = list(LAYERS) + list(ADAPTERS)   # base layers first, then sources


def run_one(client, key: str, run_date: date | None = None, **ctx_kwargs) -> RunOutcome:
    run_date = run_date or date.today()
    if key in LAYERS:
        fn = LAYERS[key]
        return tracked_run(key, lambda conn, run_id: fn(conn, run_id, client, run_date, **ctx_kwargs))
    if key in ADAPTERS:
        return run_adapter(
            ADAPTERS[key],
            lambda conn, run_id: RunContext(conn=conn, run_id=run_id, run_date=run_date,
                                            client=client, **ctx_kwargs))
    raise SystemExit(f"unknown source {key!r}; choose from {', '.join(ORDER)} or all")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="territory.run")
    ap.add_argument("--client", required=True)
    ap.add_argument("--source", help="source key or 'all' (not needed with --only-ai)")
    ap.add_argument("--only-ai", action="store_true", help="skip collection; run only the AI tasks")
    ap.add_argument("--skip-ai", action="store_true", help="never run the AI tasks")
    ap.add_argument("--tasks", help="with --only-ai: comma-separated AI tasks to run (default: permit_intent,lead_brief,weekly_brief)")
    args = ap.parse_args(argv)
    if args.only_ai and args.skip_ai:
        ap.error("--only-ai and --skip-ai cannot be combined")
    if not args.only_ai and not args.source:
        ap.error("--source is required unless --only-ai is given")
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None
    if tasks and not args.only_ai:
        ap.error("--tasks needs --only-ai")
    if tasks and (bad := [t for t in tasks if t not in ("permit_intent", "lead_brief", "weekly_brief")]):
        ap.error(f"unknown AI task(s): {', '.join(bad)}")
    client = load_client(args.client)
    if args.only_ai:
        return run_ai_step(client, tasks)
    keys = ORDER if args.source == "all" else [args.source]
    outcomes = [run_one(client, k) for k in keys]
    bad = 0
    for o in outcomes:
        print(f"{o.source_key:20s} {o.status:8s} fetched={o.rows_fetched} matched={o.rows_matched} "
              f"unmatched={o.rows_unmatched} signals={o.signals_written}"
              + (f"  error={o.error}" if o.error else ""))
        if o.status == "failed" and o.error != AWAITING_MESSAGE:
            bad += 1
    if args.source == "all" and not args.skip_ai:     # full pipeline: AI runs last (after scoring and aggregate refresh)
        run_ai_step(client)
    return 1 if bad else 0


def run_ai_step(client, tasks: list[str] | None = None) -> int:
    """permit_intent, lead_brief, weekly_brief, in that order (or only `tasks`). Skips cleanly when AI is disabled or has no key."""
    from territory.db import connect, refresh_dashboard_aggregates
    from territory.llm.runner import run_ai
    refresh_dashboard_aggregates()
    with connect(autocommit=True) as conn:
        run_ai(conn, client, tasks=tasks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
