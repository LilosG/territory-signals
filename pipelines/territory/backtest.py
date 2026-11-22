"""Deterministic historical backtest: were past sales visible from public signals beforehand?

    python -m territory.backtest --client kaiser-team [--months 24] [--as-of YYYY-MM-DD] [--cloud]

For every recorded sale in ``sales_history`` inside the trailing window (default 24 months) the runner
looks for a *live* public signal on the same parcel dated 14 to 365 days BEFORE the sale. A sale is
"flagged before sale" when at least one such signal exists; its days-early value is the distance to the
earliest qualifying signal (how long the lead would have been on the radar). Transfers by death, trust or
inheritance are not sales and are excluded.

Only public, non-owner signals are used: development permits, STR licenses, tax-default listings, code
enforcement cases and the in-house upzoning estimates. No AI, no network, no randomness. One row is
written to ``backtest_runs`` per execution; ``is_sample`` is true when any evaluable sale or matched
signal is sample data.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from dateutil.relativedelta import relativedelta
from psycopg.types.json import Jsonb

from territory.config import load_client
from territory.db import connect
from territory.scoring_engine import load_scoring_config, norm_doc_type

# Public source_key -> the signal types it can contribute. Signals without one of these source keys are
# not part of the backtest (owner recorders, ownership transfers, internal derivations).
PUBLIC_SIGNALS: dict[str, set[str]] = {
    "dev_permits": {"permit_approved", "permit_stalled"},
    "stro_licenses": {"stro_license_removed", "stro_license_active"},
    "tax_default": {"tax_default"},
    "code_enforcement": {"code_violation_open", "code_violation_closed"},
    "upzoning_estimate": {"sb9_lot_split_estimate", "sb79_transit_estimate"},
}
SIGNAL_TYPE_TO_GROUP = {t: key for key, types in PUBLIC_SIGNALS.items() for t in types}

DEFAULT_MONTHS = 24
DEFAULT_MIN_DAYS = 14
DEFAULT_MAX_DAYS = 365
SOURCE_KEY = "backtest"


@dataclass(frozen=True)
class BacktestSale:
    apn: str
    sale_date: date
    doc_type: str
    is_sample: bool


@dataclass(frozen=True)
class BacktestSignal:
    apn: str
    signal_date: date
    source_key: str
    signal_type: str
    signal_group: str
    is_sample: bool


def public_group(source_key: str, signal_type: str) -> Optional[str]:
    """The public source group for a signal, or None when it is not a backtest-eligible public signal."""
    if source_key in PUBLIC_SIGNALS and signal_type in PUBLIC_SIGNALS[source_key]:
        return source_key
    return SIGNAL_TYPE_TO_GROUP.get(signal_type)


def _unique_sales(sales: Iterable[BacktestSale], transfer_types: Mapping[str, Mapping[str, str]],
                  window_start: date, window_end: date) -> list[BacktestSale]:
    seen: set[tuple[str, date, str]] = set()
    out: list[BacktestSale] = []
    transfers = set(transfer_types)
    for sale in sales:
        if not (window_start <= sale.sale_date <= window_end):
            continue
        if norm_doc_type(sale.doc_type) in transfers:
            continue
        key = (sale.apn, sale.sale_date, norm_doc_type(sale.doc_type))
        if key in seen:
            continue
        seen.add(key)
        out.append(sale)
    return sorted(out, key=lambda s: (s.sale_date, s.apn, norm_doc_type(s.doc_type)))


def compute_backtest(sales: Sequence[BacktestSale], signals: Sequence[BacktestSignal],
                     window_start: date, window_end: date,
                     transfer_types: Optional[Mapping[str, Mapping[str, str]]] = None,
                     min_days: int = DEFAULT_MIN_DAYS, max_days: int = DEFAULT_MAX_DAYS) -> dict[str, Any]:
    """Pure, deterministic backtest. Returns the row values written to ``backtest_runs``."""
    transfers = transfer_types if transfer_types is not None else {}
    unique = _unique_sales(sales, transfers, window_start, window_end)
    by_apn: dict[str, list[BacktestSignal]] = defaultdict(list)
    for sig in signals:
        if public_group(sig.source_key, sig.signal_type):
            by_apn[sig.apn].append(sig)

    flagged = 0
    days_early: list[int] = []
    breakdown: Counter[str] = Counter()
    sample_used = any(s.is_sample for s in unique)
    for sale in unique:
        qualifying = [s for s in by_apn.get(sale.apn, ())
                      if min_days <= (sale.sale_date - s.signal_date).days <= max_days]
        if not qualifying:
            sample_used = sample_used or sale.is_sample
            continue
        flagged += 1
        days_early.append(min((sale.sale_date - s.signal_date).days for s in qualifying))
        groups = sorted({public_group(s.source_key, s.signal_type) for s in qualifying} - {None})
        for group in groups:
            breakdown[str(group)] += 1
        sample_used = sample_used or sale.is_sample or any(s.is_sample for s in qualifying)

    total = len(unique)
    return {
        "window_start": window_start,
        "window_end": window_end,
        "min_days": min_days,
        "max_days": max_days,
        "total_sales_evaluated": total,
        "flagged_before_sale_count": flagged,
        "capture_rate_pct": round(flagged * 100.0 / total, 1) if total else 0.0,
        "median_days_early": float(statistics.median(days_early)) if days_early else None,
        "avg_days_early": round(sum(days_early) / len(days_early), 1) if days_early else None,
        "breakdown_by_signal_group": dict(sorted(breakdown.items())),
        "is_sample": bool(sample_used),
    }


def load_sales(conn, window_start: date, window_end: date) -> list[BacktestSale]:
    return [BacktestSale(r[0], r[1], r[2] or "", bool(r[3])) for r in conn.execute(
        "select apn, sale_date, doc_type, is_sample from sales_history "
        "where sale_date is not null and sale_date >= %s and sale_date <= %s",
        (window_start, window_end))]


def load_public_signals(conn, window_start: date, window_end: date,
                        min_days: int, max_days: int) -> list[BacktestSignal]:
    """Live public signals that could precede a sale in the window."""
    return [BacktestSignal(r[0], r[1], r[2], r[3], r[4], bool(r[5])) for r in conn.execute(
        "select apn, signal_date, source_key, signal_type, signal_group, is_sample from signals "
        "where superseded_by is null and signal_date is not null "
        "and signal_date >= %s and signal_date <= %s and source_key = any(%s)",
        (window_start - relativedelta(days=max_days), window_end - relativedelta(days=min_days),
         list(PUBLIC_SIGNALS)))]


def run_backtest(conn, client, as_of: Optional[date] = None, months: int = DEFAULT_MONTHS,
                 min_days: int = DEFAULT_MIN_DAYS, max_days: int = DEFAULT_MAX_DAYS,
                 write: bool = True) -> dict[str, Any]:
    as_of = as_of or date.today()
    window_start = as_of - relativedelta(months=months)
    cfg = load_scoring_config()
    sales = load_sales(conn, window_start, as_of)
    signals = load_public_signals(conn, window_start, as_of, min_days, max_days)
    result = compute_backtest(sales, signals, window_start, as_of, cfg["transfer_types"], min_days, max_days)
    result.update({"client_id": client.client_id, "months": months,
                   "computed_at": datetime.now(timezone.utc)})
    if write:
        conn.execute(
            "insert into backtest_runs (client_id, window_start, window_end, months, min_days, max_days, "
            "total_sales_evaluated, flagged_before_sale_count, capture_rate_pct, median_days_early, "
            "avg_days_early, breakdown_by_signal_group, is_sample, computed_at) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (result["client_id"], result["window_start"], result["window_end"], months, min_days, max_days,
             result["total_sales_evaluated"], result["flagged_before_sale_count"], result["capture_rate_pct"],
             result["median_days_early"], result["avg_days_early"], Jsonb(result["breakdown_by_signal_group"]),
             result["is_sample"], result["computed_at"]))
        conn.commit()
    return result


def _summary(r: Mapping[str, Any]) -> str:
    med = r["median_days_early"]
    return (f"backtest {r['window_start']} to {r['window_end']}: {r['flagged_before_sale_count']} of "
            f"{r['total_sales_evaluated']} sales flagged before sale "
            f"({r['capture_rate_pct']}% capture, median {med if med is not None else '-'} days early); "
            f"sample={r['is_sample']}; by source {r['breakdown_by_signal_group']}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="territory.backtest")
    ap.add_argument("--client", required=True)
    ap.add_argument("--cloud", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="default: today")
    ap.add_argument("--months", type=int, default=DEFAULT_MONTHS, help="trailing window (default 24)")
    ap.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS)
    ap.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS)
    args = ap.parse_args(argv)
    client = load_client(args.client)
    with connect() as conn:
        result = run_backtest(conn, client, args.as_of, args.months, args.min_days, args.max_days)
    print(_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
