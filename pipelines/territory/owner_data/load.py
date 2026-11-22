"""Load owners and sales_history for every residential parcel from the client's owner-data
provider (the labeled SampleOwnerProvider until ATTOM is configured, D9).

    python -m territory.owner_data.load --client kaiser-team

Append-only: a new owners row per (apn, provider, as_of); nothing is updated. Rerunning on
the same day adds nothing. Sample rows keep provider='sample', is_sample=true.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date

from psycopg.types.json import Jsonb

from territory.config import load_client
from territory.db import connect, refresh_dashboard_aggregates
from territory.owner_data.attom import AttomOwnerProvider
from territory.owner_data.sample import SampleOwnerProvider
from territory.portfolio import recompute_portfolios
from territory.scoring_engine import load_scoring_config, norm_doc_type

BATCH = 2000


def provider_for(client):
    return SampleOwnerProvider() if client.owner_data_provider == "sample" else AttomOwnerProvider()


def _num(v):
    return None if v is None else float(v)


def residential_apns(conn, codes) -> list[str]:
    return [r[0] for r in conn.execute(
        "select apn from parcels where land_use = any(%s) order by apn", (list(codes),))]


def load_owner_layer(conn, client, as_of: date, cfg=None) -> dict[str, int]:
    cfg = cfg or load_scoring_config()
    provider = provider_for(client)
    apns = residential_apns(conn, cfg["residential_codes"])
    name = provider.provider
    # Append-only: an owner row identical to one already stored for this as_of is skipped; a row whose
    # content changed (e.g. a corrected last_sale_date) is appended and wins by created_at in readers.
    have_owner = {(r[0], r[1], r[2], _num(r[3])) for r in conn.execute(
        "select apn, owner_name, last_sale_date, last_sale_price from owners where provider=%s and as_of=%s",
        (name, as_of))}
    have_sale = {(r[0], r[1], r[2]) for r in conn.execute(
        "select apn, sale_date, doc_type from sales_history where provider=%s", (name,))}
    types = cfg["transfer_types"]
    owners = sales = transfers = 0
    for i in range(0, len(apns), BATCH):
        chunk = apns[i:i + BATCH]
        o_rows, s_rows, t_rows = [], [], []
        for apn in chunk:
            o = replace(provider.get_owner(apn), as_of=as_of)
            if (o.apn, o.owner_name, o.last_sale_date, _num(o.last_sale_price)) not in have_owner:
                o_rows.append((o.apn, o.owner_name, o.mailing_address, o.owner_occupied, o.absentee,
                               o.out_of_state, o.last_sale_date, o.last_sale_price, o.mortgage_open,
                               o.est_value, o.est_equity, o.provider, o.is_sample, o.as_of))
            for s in provider.get_sales_history(apn):
                kind = types.get(norm_doc_type(s.doc_type))
                if kind and s.sale_date:
                    # Phase 6 activates quiet_inheritance from these; they never score and never suppress.
                    t_rows.append((
                        s.apn, "ownership_transfer", "life_event", s.sale_date, f"{s.provider}_sales_history",
                        f"{s.apn}:{s.sale_date}:{norm_doc_type(s.doc_type)}", s.confidence, "apn", s.is_sample,
                        Jsonb({"doc_type": s.doc_type, "transfer_kind": kind["kind"], "label": kind["label"]})))
                if (s.apn, s.sale_date, s.doc_type) not in have_sale:
                    have_sale.add((s.apn, s.sale_date, s.doc_type))
                    s_rows.append((s.apn, s.sale_date, s.sale_price, s.doc_type, s.provider, s.is_sample))
        with conn.cursor() as cur:
            cur.executemany(
                "insert into owners (apn, owner_name, mailing_address, owner_occupied, absentee, "
                "out_of_state, last_sale_date, last_sale_price, mortgage_open, est_value, est_equity, "
                "provider, is_sample, as_of) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", o_rows)
            cur.executemany(
                "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
                "confidence, match_method, is_sample, details) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict on constraint signals_natural_key do nothing", t_rows)
            transfers += max(0, cur.rowcount) if t_rows else 0
            cur.executemany(
                "insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) "
                "values (%s,%s,%s,%s,%s,%s)", s_rows)
        owners += len(o_rows)
        sales += len(s_rows)
    conn.commit()
    return {"residential_parcels": len(apns), "owners_inserted": owners, "sales_inserted": sales,
            "transfer_signals": transfers}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.owner_data.load")
    ap.add_argument("--client", required=True)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="default: today")
    args = ap.parse_args(argv)
    client = load_client(args.client)
    with connect() as conn:
        res = load_owner_layer(conn, client, args.as_of or date.today())
        # The portfolio layer is derived from the owners snapshot, so refresh it in the same command.
        res["portfolios"] = recompute_portfolios(conn, args.as_of)
    refresh_dashboard_aggregates()
    print(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
