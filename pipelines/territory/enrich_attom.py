"""ATTOM enrichment CLI and reusable owner-loading stages.

    python -m territory.enrich_attom --client kaiser-team --limit 250 --max-calls 450 [--cloud]

Selects the highest-priority residential parcels (non-sample signal points, then builder-bait / STR /
tax-default candidates), loads their real ATTOM owner, mailing, value, mortgage and recorder history,
writes real rows with ``provider='attom', is_sample=false`` and emits recorder signals, then refreshes
the portfolio layer, scores, runs the historical backtest and rebuilds the dashboard aggregates.

In hybrid mode every parcel that is not enriched keeps its labeled ``SampleOwnerProvider`` row. When an
ATTOM response has no property for a selected parcel, the same command writes that parcel's labeled
sample fallback (unless an identical row already exists).

No live network call happens unless a real API key is present; tests inject recorded fixtures through
``fetcher`` and spend $0.00.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional

from psycopg.types.json import Jsonb

from territory.backtest import run_backtest
from territory.config import load_client
from territory.db import connect, refresh_dashboard_aggregates
from territory.owner_data.attom import (
    AttomOwnerProvider, Fetcher, NotConfiguredError, QuotaExceededError, recorder_signal_candidates,
)
from territory.owner_data.sample import SampleOwnerProvider
from territory.portfolio import recompute_portfolios
from territory.score import run_score
from territory.scoring_engine import load_scoring_config, norm_doc_type

SOURCE_KEY = "attom"
DEFAULT_LIMIT = 250
DEFAULT_MAX_CALLS = 450


@dataclass
class EnrichResult:
    selected: int = 0
    attom_owners: int = 0
    sample_fallback_owners: int = 0
    sales_inserted: int = 0
    inheritance_signals: int = 0
    notice_signals: int = 0
    calls_made: int = 0
    cache_hits: int = 0
    stopped: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {"selected": self.selected, "attom_owners": self.attom_owners,
                "sample_fallback_owners": self.sample_fallback_owners,
                "sales_inserted": self.sales_inserted,
                "inheritance_signals": self.inheritance_signals,
                "notice_signals": self.notice_signals,
                "calls_made": self.calls_made, "cache_hits": self.cache_hits,
                "stopped": self.stopped, **self.extras}


# ---------------------------------------------------------------------------------------
# prioritization
# ---------------------------------------------------------------------------------------
def _component_points(components: Any) -> float:
    if not isinstance(components, list):
        return 0.0
    total = 0.0
    for c in components:
        if isinstance(c, Mapping) and c.get("kind") == "signal" and not c.get("is_sample"):
            try:
                total += float(c.get("contribution") or 0)
            except (TypeError, ValueError):
                pass
    return round(total, 4)


def _candidate(recipe_matches: Any, components: Any) -> bool:
    recipes = set(recipe_matches or ())
    keys = {c.get("key") for c in components or () if isinstance(c, Mapping)}
    return bool(recipes & {"builder_bait"} or
                any(str(k).startswith("stro_license") for k in keys) or
                any(k in ("tax_default", "notice_of_default") for k in keys))


def ranked_apns(conn, cfg: Mapping[str, Any], limit: int) -> list[dict[str, Any]]:
    """Residential parcels in enrichment priority order (candidates first, then non-sample points)."""
    rows = conn.execute(
        "select s.apn, s.score, s.components, s.recipe_matches, p.situs_address "
        "  from latest_scores s join parcels p on p.apn = s.apn "
        " where p.land_use = any(%s)", (cfg["residential_codes"],)).fetchall()
    items = []
    for apn, score, components, recipes, situs in rows:
        points = _component_points(components)
        items.append({"apn": apn, "situs_address": situs, "score": int(score or 0),
                      "non_sample_points": points, "candidate": _candidate(recipes, components)})
    items.sort(key=lambda x: (not x["candidate"], -x["non_sample_points"], -x["score"], x["apn"]))
    if not items:  # no scores yet: still enrich the top residential parcels deterministically
        items = [{"apn": r[0], "situs_address": r[1], "score": 0, "non_sample_points": 0.0,
                  "candidate": False} for r in conn.execute(
            "select apn, situs_address from parcels where land_use = any(%s) order by apn limit %s",
            (cfg["residential_codes"], limit))]
    return items[:max(0, limit)]


# ---------------------------------------------------------------------------------------
# enrichment
# ---------------------------------------------------------------------------------------
def _existing(conn, provider: str, as_of: date) -> set[tuple]:
    return {(r[0], r[1], r[2], float(r[3]) if r[3] is not None else None) for r in conn.execute(
        "select apn, owner_name, last_sale_date, last_sale_price from owners where provider=%s and as_of=%s",
        (provider, as_of))}


def _insert_owner(conn, owner, values: tuple) -> int:
    if owner is None:
        return 0
    conn.execute(
        "insert into owners (apn, owner_name, mailing_address, owner_occupied, absentee, out_of_state, "
        "last_sale_date, last_sale_price, mortgage_open, est_value, est_equity, provider, is_sample, as_of) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", values)
    return 1


def enrich_owners(conn, client, *, limit: int = DEFAULT_LIMIT, max_calls: int = DEFAULT_MAX_CALLS,
                  refresh_days: Optional[int] = None, as_of: Optional[date] = None,
                  fetcher: Optional[Fetcher] = None, sample_fallback: bool = True) -> EnrichResult:
    """Load ATTOM owners/recorder history for prioritized parcels. Does not score or run the backtest."""
    as_of = as_of or date.today()
    cfg = load_scoring_config()
    result = EnrichResult()
    selected = ranked_apns(conn, cfg, limit)
    result.selected = len(selected)
    if client.owner_data_provider == "sample" and fetcher is None:
        raise NotConfiguredError(
            "owner_data_provider is 'sample'. Set it to 'hybrid' or 'attom' (config/clients/<id>.yaml) "
            "before running territory.enrich_attom.")
    provider = AttomOwnerProvider(conn=conn, max_calls=max_calls, refresh_days=refresh_days,
                                  as_of=as_of, fetcher=fetcher)
    sample = SampleOwnerProvider()
    have_attom = _existing(conn, "attom", as_of)
    have_sample = _existing(conn, "sample", as_of)
    have_sale = {(r[0], r[1], r[2], r[3]) for r in conn.execute(
        "select provider, apn, sale_date, doc_type from sales_history where provider in ('attom', 'sample')")}

    for item in selected:
        apn, address = item["apn"], item["situs_address"]
        try:
            owner = provider.get_owner(apn, address)
            docs = provider.get_recorder_documents(apn, address)
        except QuotaExceededError as exc:      # type: ignore[name-defined]
            result.stopped = str(exc)
            break
        if owner is not None:
            key = (owner.apn, owner.owner_name, owner.last_sale_date, owner.last_sale_price)
            if key not in have_attom:
                result.attom_owners += _insert_owner(conn, owner, (
                    owner.apn, owner.owner_name, owner.mailing_address, owner.owner_occupied, owner.absentee,
                    owner.out_of_state, owner.last_sale_date, owner.last_sale_price, owner.mortgage_open,
                    owner.est_value, owner.est_equity, owner.provider, owner.is_sample, owner.as_of))
                have_attom.add(key)
            for sale in provider.get_sales_history(apn, address):
                skey = (sale.provider, sale.apn, sale.sale_date, sale.doc_type)
                if skey not in have_sale:
                    conn.execute(
                        "insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) "
                        "values (%s,%s,%s,%s,%s,%s)",
                        (sale.apn, sale.sale_date, sale.sale_price, sale.doc_type, sale.provider, sale.is_sample))
                    have_sale.add(skey)
                    result.sales_inserted += 1
            run_id = provider._ensure_run()
            for cand in recorder_signal_candidates(apn, docs):
                sid = f"attom:{apn}:{cand['signal_date']}:{norm_doc_type(cand['doc_type'])}"
                cur = conn.execute(
                    "insert into signals (apn, signal_type, signal_group, signal_date, source_key, "
                    "source_record_id, run_id, confidence, match_method, is_sample, details) "
                    "values (%s,%s,%s,%s,'attom',%s,%s,1.0,'apn',false,%s) "
                    "on conflict on constraint signals_natural_key do nothing",
                    (apn, cand["signal_type"], cand["signal_group"], cand["signal_date"], sid, run_id,
                     Jsonb({k: cand[k] for k in ("doc_type", "label") if k in cand}
                           | ({k: cand[k] for k in ("transfer_kind", "notice_kind") if k in cand}))))
                if cur.rowcount:
                    if cand["signal_type"] == "ownership_transfer_inheritance":
                        result.inheritance_signals += 1
                    else:
                        result.notice_signals += 1
        elif sample_fallback and client.owner_data_provider == "hybrid":
            o = sample.get_owner(apn)
            key = (o.apn, o.owner_name, o.last_sale_date, float(o.last_sale_price) if o.last_sale_price is not None else None)
            if key not in have_sample:
                result.sample_fallback_owners += _insert_owner(conn, o, (
                    o.apn, o.owner_name, o.mailing_address, o.owner_occupied, o.absentee, o.out_of_state,
                    o.last_sale_date, o.last_sale_price, o.mortgage_open, o.est_value, o.est_equity,
                    o.provider, o.is_sample, as_of))
                have_sample.add(key)
            for sale in sample.get_sales_history(apn):
                skey = (sale.provider, sale.apn, sale.sale_date, sale.doc_type)
                if skey not in have_sale:
                    conn.execute(
                        "insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) "
                        "values (%s,%s,%s,%s,%s,%s)",
                        (sale.apn, sale.sale_date, sale.sale_price, sale.doc_type, sale.provider, sale.is_sample))
                    have_sale.add(skey)
                    result.sales_inserted += 1

    provider.close_run("success" if result.stopped is None else "failed",
                       rows_fetched=result.selected, rows_matched=result.attom_owners,
                       rows_unmatched=result.selected - result.attom_owners)
    result.calls_made, result.cache_hits = provider.calls_made, provider.cache_hits
    conn.commit()
    return result


def enrich_and_refresh(conn, client, *, limit: int = DEFAULT_LIMIT, max_calls: int = DEFAULT_MAX_CALLS,
                       refresh_days: Optional[int] = None, as_of: Optional[date] = None,
                       fetcher: Optional[Fetcher] = None) -> dict[str, Any]:
    """Enrich, then rebuild portfolios, scores, backtest and dashboard aggregates (the CLI's work)."""
    as_of = as_of or date.today()
    result = enrich_owners(conn, client, limit=limit, max_calls=max_calls, refresh_days=refresh_days,
                           as_of=as_of, fetcher=fetcher)
    extras: dict[str, Any] = {}
    extras["portfolios"] = recompute_portfolios(conn, as_of)
    extras["score"] = run_score(conn, load_scoring_config(), as_of)
    extras["backtest"] = run_backtest(conn, client, as_of)
    extras["aggregates_refreshed"] = refresh_dashboard_aggregates()
    result.extras = {k: (v if k != "score" else {"scored": v["scored"], "model_version": v["model_version"]})
                     for k, v in extras.items()}
    return result.summary()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="territory.enrich_attom")
    ap.add_argument("--client", required=True)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="parcels to enrich (default 250)")
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                    help="strict ATTOM API calls per day (default 450)")
    ap.add_argument("--refresh-days", type=int, default=None,
                    help="refetch a cached parcel only after this many days (default: never)")
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="default: today")
    ap.add_argument("--cloud", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    client = load_client(args.client)
    with connect() as conn:
        summary = enrich_and_refresh(conn, client, limit=args.limit, max_calls=args.max_calls,
                                     refresh_days=args.refresh_days, as_of=args.as_of)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
