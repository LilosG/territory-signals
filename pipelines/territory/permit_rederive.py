"""Phase 3: re-derive permit signals from the final permit map and the stalled rule.

    python -m territory.permit_rederive --client kaiser-team

Deterministic and append-only. For every approval that already has a live permit signal,
the latest stored raw record is run through territory/permit_rules.py. Then, per
(approval, signal type):
  - same group and date as the live signal  -> nothing to do
  - different, or no longer derived         -> the old row is stamped superseded_by = this run
  - newly derived (new group/date)          -> a new row is inserted with run_id = this run
    (also when the group is one the approval once had: the unique key includes superseded_by,
    so a reinstated group gets a fresh live row)
Nothing is deleted or overwritten (the one permitted UPDATE is superseded_by null -> run id).
The parcel link (apn, confidence, match_method) is copied from the signal being replaced.
A report with live counts before and after is written to sources/reports/.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, datetime

from psycopg.types.json import Jsonb

from territory import permit_rules as rules
from territory.config import load_client
from territory.reports import REPORT_DIR
from territory.scoring_engine import load_scoring_config
from territory.runner import WorkResult, clean_json, tracked_run

SOURCE_KEY = "permit_rederive"
PERMIT_TYPES = ("permit_approved", "permit_stalled")


def live_counts(conn) -> Counter:
    return Counter({(t, g): n for t, g, n in conn.execute(
        "select signal_type, signal_group, count(*) from signals "
        "where signal_type = any(%s) and superseded_by is null group by 1,2", (list(PERMIT_TYPES),))})


def rederive(conn, run_id: str, run_date: date, map_path=None) -> dict:
    mapping = rules.load_map(map_path)
    live = conn.execute(
        "select id, apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
        "confidence, match_method, is_estimate, is_sample from signals "
        "where signal_type = any(%s) and superseded_by is null order by source_record_id, signal_type",
        (list(PERMIT_TYPES),)).fetchall()
    by_key = {(r[6], r[2]): r for r in live}
    approvals = sorted({r[6] for r in live})
    link = {}                                   # approval -> (apn, confidence, method) from any live row
    for r in live:
        link.setdefault(r[6], (r[1], r[7], r[8], r[5]))
    codes = load_scoring_config()["residential_codes"]
    res_apns = {r[0] for r in conn.execute("select apn from parcels where land_use = any(%s)", (codes,))}
    before = live_counts(conn)
    superseded: list[str] = []
    inserted = 0
    changed = Counter()
    seen_raw: set[str] = set()
    for i in range(0, len(approvals), 2000):
        chunk = approvals[i:i + 2000]
        raws = conn.execute(
            "select distinct on (source_record_id) source_record_id, payload from raw_records "
            "where source_key='dev_permits' and source_record_id = any(%s) "
            "order by source_record_id, fetched_at desc", (chunk,)).fetchall()
        for aid, payload in raws:
            seen_raw.add(aid)
            apn, conf, method, source_key = link[aid]
            derived = {s["signal_type"]: s for s in rules.derive(
                payload, aid, mapping["approval_types"], run_date, apn in res_apns,
                mapping["residential_remodel_types"], mapping["presale_rules"])}
            for stype in PERMIT_TYPES:
                old, new = by_key.get((aid, stype)), derived.get(stype)
                same = (old is not None and new is not None and old[3] == new["group"]
                        and old[4] == new["signal_date"])
                if same or (old is None and new is None):
                    continue
                if old is not None:
                    superseded.append(old[0])
                    changed[(stype, old[3], new["group"] if new else "(retired)")] += 1
                if new is not None:
                    if old is None:
                        # a signal that was not live before (e.g. stalled newly qualifies)
                        old_conf, old_method = conf, method
                    else:
                        old_conf, old_method = old[7], old[8]
                    details = {**new["details"], "rederived": True,
                               "previous_group": old[3] if old else None}
                    cur = conn.execute(
                        "insert into signals (apn, signal_type, signal_group, signal_date, source_key, "
                        "source_record_id, run_id, confidence, match_method, is_estimate, is_sample, details) "
                        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,false,false,%s) "
                        "on conflict on constraint signals_natural_key do nothing",
                        (apn, stype, new["group"], new["signal_date"], source_key, aid, run_id,
                         old_conf, old_method, Jsonb(clean_json(details))))
                    inserted += cur.rowcount
    missing_raw = [a for a in approvals if a not in seen_raw]
    # Live signals whose raw record is gone cannot be re-derived: leave them untouched.
    for i in range(0, len(superseded), 2000):
        conn.execute("update signals set superseded_by=%s where id = any(%s)",
                     (run_id, superseded[i:i + 2000]))
    after = live_counts(conn)
    return {"before": before, "after": after, "superseded": len(superseded), "inserted": inserted,
            "approvals_checked": len(approvals), "missing_raw": len(missing_raw), "changed": changed,
            "map_status": mapping["status"]}


def write_report(res: dict, run_date: date, report_dir=None) -> None:
    d = report_dir or REPORT_DIR
    d.mkdir(parents=True, exist_ok=True)
    keys = sorted(set(res["before"]) | set(res["after"]))
    lines = [f"# Permit signal re-derivation", "", f"Run date {run_date}; permit map status: {res['map_status']}.",
             "", f"- approvals checked: {res['approvals_checked']}",
             f"- signals superseded: {res['superseded']}", f"- signals inserted: {res['inserted']}",
             f"- approvals with no raw record (left untouched): {res['missing_raw']}", "",
             "## Live permit signals before and after", "", "| signal_type | group | before | after |",
             "|---|---|---|---|"]
    for t, g in keys:
        lines.append(f"| {t} | {g} | {res['before'].get((t, g), 0)} | {res['after'].get((t, g), 0)} |")
    lines += ["", "## Changes", "", "| signal_type | from group | to group | rows |", "|---|---|---|---|"]
    for (t, o, n), c in sorted(res["changed"].items()):
        lines.append(f"| {t} | {o} | {n} | {c} |")
    (d / "permit_rederive_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.permit_rederive")
    ap.add_argument("--client", required=True)
    ap.add_argument("--run-date", type=date.fromisoformat, default=None, help="default: today")
    args = ap.parse_args(argv)
    load_client(args.client)                    # validates the client id
    run_date = args.run_date or date.today()
    out: dict = {}

    def work(conn, run_id: str) -> WorkResult:
        out.update(rederive(conn, run_id, run_date))
        return WorkResult(rows_fetched=out["approvals_checked"], signals_written=out["inserted"])

    outcome = tracked_run(SOURCE_KEY, work)
    if outcome.status != "success":
        print(f"failed: {outcome.error}")
        return 1
    write_report(out, run_date)
    print(f"superseded={out['superseded']} inserted={out['inserted']} checked={out['approvals_checked']}")
    for k in sorted(set(out["before"]) | set(out["after"])):
        print(f"{k[0]:16s} {k[1]:22s} before={out['before'].get(k, 0):6d} after={out['after'].get(k, 0):6d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
