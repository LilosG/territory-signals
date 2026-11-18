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
    ap.add_argument("--source", required=True, help="source key or 'all'")
    args = ap.parse_args(argv)
    client = load_client(args.client)
    keys = ORDER if args.source == "all" else [args.source]
    outcomes = [run_one(client, k) for k in keys]
    bad = 0
    for o in outcomes:
        print(f"{o.source_key:20s} {o.status:8s} fetched={o.rows_fetched} matched={o.rows_matched} "
              f"unmatched={o.rows_unmatched} signals={o.signals_written}"
              + (f"  error={o.error}" if o.error else ""))
        if o.status == "failed" and o.error != AWAITING_MESSAGE:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
