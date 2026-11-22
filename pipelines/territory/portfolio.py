"""Deterministic entity and territory-portfolio clustering.

    python -m territory.portfolio --client kaiser-team [--as-of YYYY-MM-DD]

Scans the current owners snapshot (one row per APN, latest as_of) and groups parcels that share either

  (a) an exact normalized mailing address (blank/unknown addresses are ignored), or
  (b) an exact normalized corporate / trust / LLC owner name (LLC, LP, TRUST, INC, PROPERTIES, HOLDINGS, ...).

The result is written to public.parcel_portfolios (one row per parcel per recompute) and read by the
scorer's portfolio modifier and by the dashboard's "Territory Portfolio" callout. No AI, no network.
Sample owner data is carried through with is_sample = true.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Optional, Sequence

from territory.config import load_client
from territory.db import connect

UNKNOWN_ADDRESSES = {"", "-", "n a", "na", "none", "no address", "unknown", "unavailable"}
_TRUST = re.compile(r"\b(trust|trustee|trustees|estate)\b")
_CORP = re.compile(r"\b(llc|l l c|lp|l p|llp|inc|incorporated|corp|corporation|company|co|properties|holdings)\b")


@dataclass(frozen=True)
class OwnerRow:
    apn: str
    owner_name: Optional[str]
    mailing_address: Optional[str]
    absentee: Optional[bool]
    out_of_state: Optional[bool]
    est_value: Optional[float]
    est_equity: Optional[float]
    is_sample: bool


@dataclass(frozen=True)
class PortfolioRow:
    apn: str
    portfolio_key: str
    entity_type: str
    territory_parcel_count: int
    total_est_value: Optional[float]
    total_est_equity: Optional[float]
    is_sample: bool


def normalize_text(value: object) -> str:
    """Lower-case, drop punctuation, collapse whitespace. Used for both names and addresses."""
    s = " ".join(str(value or "").strip().lower().split())
    s = re.sub(r"[.,;:#]", " ", s)
    return " ".join(s.split())


def normalize_mailing(value: object) -> Optional[str]:
    """An exact normalized mailing address, or None for a blank/unknown address."""
    s = normalize_text(value)
    if not s or s in UNKNOWN_ADDRESSES:
        return None
    if not any(ch.isdigit() for ch in s):        # a street address must have a number
        return None
    return s


def normalize_owner_name(value: object) -> Optional[str]:
    s = normalize_text(value)
    return s or None


def entity_kind(name: object) -> Optional[str]:
    """'llc_corp' or 'trust' when the normalized name reads as an organization, else None."""
    s = normalize_text(name)
    if not s:
        return None
    if _CORP.search(s):
        return "llc_corp"
    if _TRUST.search(s):
        return "trust"
    return None


def _sum_optional(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [float(v) for v in values if v is not None]
    return round(sum(present), 2) if present else None


def build_portfolios(owners: Sequence[OwnerRow]) -> list[PortfolioRow]:
    """Group parcels by shared normalized mailing address or corporate/trust owner name.

    Deterministic: sorted input gives sorted output; the portfolio_key is the smallest shared key in the
    group (or apn:<apn> for a single-parcel portfolio)."""
    if not owners:
        return []
    parent = {o.apn: o.apn for o in owners}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    keys_by_apn: dict[str, list[str]] = {}
    key_members: dict[str, list[str]] = defaultdict(list)
    for o in owners:
        keys: list[str] = []
        name = normalize_owner_name(o.owner_name)
        if name and entity_kind(name):
            keys.append(f"name:{name}")
        mail = normalize_mailing(o.mailing_address)
        if mail:
            keys.append(f"mail:{mail}")
        keys_by_apn[o.apn] = keys
        for k in keys:
            key_members[k].append(o.apn)
    for members in key_members.values():
        if len(members) >= 2:
            for apn in members[1:]:
                union(members[0], apn)

    groups: dict[str, list[OwnerRow]] = defaultdict(list)
    for o in owners:
        groups[find(o.apn)].append(o)

    rows: list[PortfolioRow] = []
    for members in groups.values():
        apns = sorted(m.apn for m in members)
        size = len(apns)
        keys = sorted({k for apn in apns for k in keys_by_apn.get(apn, [])})
        kinds = {entity_kind(k[5:]) for k in keys if k.startswith("name:")}
        if "llc_corp" in kinds:
            entity_type = "llc_corp"
        elif "trust" in kinds:
            entity_type = "trust"
        elif size >= 2:
            entity_type = "individual_multi"
        else:
            entity_type = "single"
        portfolio_key = (min([k for k in keys if k.startswith("name:")] or
                             [k for k in keys if k.startswith("mail:")])
                         if size >= 2 and keys else f"apn:{apns[0]}")
        total_value = _sum_optional(m.est_value for m in members)
        total_equity = _sum_optional(m.est_equity for m in members)
        sample = any(m.is_sample for m in members)
        for apn in apns:
            rows.append(PortfolioRow(apn, portfolio_key, entity_type, size,
                                     total_value, total_equity, sample))
    return sorted(rows, key=lambda r: (r.portfolio_key, r.apn))


OWNER_SQL = """
select distinct on (apn) apn, owner_name, mailing_address, absentee, out_of_state,
       est_value, est_equity, is_sample
  from owners
 {where}
 order by apn, as_of desc, (provider = 'attom') desc, created_at desc
"""


def load_current_owners(conn, as_of: date | None = None) -> list[OwnerRow]:
    sql = OWNER_SQL.format(where="where as_of <= %s" if as_of else "")
    params = (as_of,) if as_of else ()
    return [OwnerRow(r[0], r[1], r[2], r[3], r[4],
                     float(r[5]) if r[5] is not None else None,
                     float(r[6]) if r[6] is not None else None,
                     bool(r[7]))
            for r in conn.execute(sql, params)]


def summarize(rows: Sequence[PortfolioRow]) -> dict:
    multi = [r for r in rows if r.territory_parcel_count >= 2]
    groups = {r.portfolio_key: r for r in multi}
    return {
        "parcels": len(rows),
        "portfolios": len(groups),
        "multi_parcel_parcels": len(multi),
        "portfolios_by_entity": dict(Counter(r.entity_type for r in groups.values())),
        "parcels_by_entity": dict(Counter(r.entity_type for r in rows)),
        "sample_parcels": sum(1 for r in rows if r.is_sample),
    }


def recompute_portfolios(conn, as_of: date | None = None,
                         computed_at: datetime | None = None) -> dict:
    """Rebuild public.parcel_portfolios from the current owners snapshot. Returns a summary."""
    computed_at = computed_at or datetime.now(timezone.utc)
    rows = build_portfolios(load_current_owners(conn, as_of))
    with conn.cursor() as cur:
        cur.execute("delete from parcel_portfolios")
        cur.executemany(
            "insert into parcel_portfolios (apn, portfolio_key, entity_type, territory_parcel_count, "
            "total_est_value, total_est_equity, is_sample, computed_at) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s)",
            [(r.apn, r.portfolio_key, r.entity_type, r.territory_parcel_count,
              r.total_est_value, r.total_est_equity, r.is_sample, computed_at) for r in rows])
    conn.commit()
    return summarize(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="territory.portfolio")
    ap.add_argument("--client", required=True)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None,
                    help="use owners with as_of on or before this date (default: latest)")
    args = ap.parse_args(argv)
    load_client(args.client)
    with connect() as conn:
        s = recompute_portfolios(conn, args.as_of)
    print(f"portfolio refresh: {s['parcels']} parcels, {s['portfolios']} multi-parcel portfolios, "
          f"{s['multi_parcel_parcels']} parcels in a portfolio; by entity {s['portfolios_by_entity']}; "
          f"sample parcels {s['sample_parcels']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
