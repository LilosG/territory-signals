"""Scoring step: python -m territory.score --client kaiser-team [--as-of YYYY-MM-DD]

Reads residential parcels, live signals (superseded_by is null), the latest owners row and
sales_history; applies suppression; writes ONE scores row per scored parcel per run
(append-only history). Deterministic: no AI, no randomness. See config/scoring.yaml.

    python -m territory.score --client kaiser-team --profile-land-use
writes sources/reports/land_use_profile.csv (distinct parcels.land_use values) and exits.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from dateutil.relativedelta import relativedelta
from psycopg.types.json import Jsonb

from territory.config import load_client
from territory.db import connect
from territory.reports import REPORT_DIR
from territory.scoring_engine import (
    Owner, Sig, latest_snapshot_dates, load_scoring_config, percentile, score_parcel,
)

BATCH = 2000
FIRE_DATA = "fire_zones"


# ---------------------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------------------
def load_residential(conn, cfg) -> list[tuple[str, str | None, str | None]]:
    """(apn, planning_area, land_use) of every parcel with a residential land-use code."""
    return conn.execute(
        "select apn, planning_area, land_use from parcels where land_use = any(%s) order by apn",
        (cfg["residential_codes"],)).fetchall()


def load_owners(conn, apns: list[str]) -> dict[str, Owner]:
    """Latest owners row per parcel (latest as_of; ATTOM beats sample on a tie)."""
    out: dict[str, Owner] = {}
    rows = conn.execute(
        "select distinct on (apn) apn, last_sale_date, owner_occupied, absentee, out_of_state, "
        "mortgage_open, est_equity, is_sample, provider, as_of from owners where apn = any(%s) "
        "order by apn, as_of desc, (provider = 'attom') desc, created_at desc", (apns,)).fetchall()
    for r in rows:
        out[r[0]] = Owner(r[1], r[2], r[3], r[4], r[5], float(r[6]) if r[6] is not None else None,
                          r[7], r[8], r[9])
    return out


def load_suppressed(conn, apns: list[str], as_of: date, months: int) -> dict[str, str]:
    """apn -> reason. Recent sale (sales_history) or an active suppressions row."""
    cutoff = as_of - relativedelta(months=months)
    out: dict[str, str] = {}
    for (apn,) in conn.execute(
            "select distinct apn from sales_history where apn = any(%s) and sale_date >= %s "
            "and sale_date <= %s", (apns, cutoff, as_of)):
        out[apn] = f"sale within {months} months"
    for apn, reason in conn.execute(
            "select apn, reason from suppressions where apn = any(%s) "
            "and (until_date is null or until_date >= %s)", (apns, as_of)):
        out[apn] = f"suppression: {reason}"
    return out


def load_signals(conn, apns: list[str], types: list[str]) -> dict[str, list[Sig]]:
    by_apn: dict[str, list[Sig]] = defaultdict(list)
    for r in conn.execute(
            "select id, apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
            "confidence, match_method, is_estimate, is_sample, details from signals "
            "where superseded_by is null and signal_type = any(%s) and apn = any(%s)", (types, apns)):
        by_apn[r[1]].append(Sig(str(r[0]), r[2], r[3], r[4], r[5], r[6], float(r[7]), r[8],
                                r[9], r[10], r[11] or {}))
    return by_apn


def load_snapshot_dates(conn, cfg) -> dict[str, date]:
    snaps = [t for t, c in cfg["signals"].items() if c.get("snapshot")]
    return {t: d for t, d in conn.execute(
        "select signal_type, max(signal_date) from signals where superseded_by is null "
        "and signal_type = any(%s) group by 1", (snaps,)) if d is not None}


def loaded_data(conn) -> list[str]:
    n = conn.execute("select count(*) from signals where signal_type='fire_hazard_zone' "
                     "and superseded_by is null").fetchone()[0]
    return [FIRE_DATA] if n else []


# ---------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------
def run_score(conn, cfg: Mapping[str, Any], as_of: date, scored_at: datetime | None = None) -> dict[str, Any]:
    scored_at = scored_at or datetime.now(timezone.utc)
    parcels = load_residential(conn, cfg)
    apns = [p[0] for p in parcels]
    owners = load_owners(conn, apns)
    suppressed = load_suppressed(conn, apns, as_of, cfg["suppression"]["recent_sale_months"])
    sigs = load_signals(conn, apns, list(cfg["signals"]))
    snap = load_snapshot_dates(conn, cfg)
    data = loaded_data(conn)
    cutoff = percentile([o.est_equity for o in owners.values() if o.est_equity is not None],
                        cfg["owner_modifiers"]["est_equity_top_quartile"]["percentile"])
    rows, area_of = [], {}
    summary: dict[str, Any] = {
        "model_version": cfg["model_version"], "as_of": str(as_of), "residential_parcels": len(parcels),
        "suppressed": Counter(), "scored": 0, "equity_cutoff": cutoff, "loaded_data": data,
        "non_residential_parcels": conn.execute("select count(*) from parcels").fetchone()[0] - len(parcels)}
    for apn, area, _land_use in parcels:
        if apn in suppressed:
            summary["suppressed"][suppressed[apn].split(":")[0]] += 1
            continue
        r = score_parcel(sigs.get(apn, []), owners.get(apn), cfg, as_of, snap, cutoff, data)
        area_of[apn] = area
        rows.append((apn, r["score"], Jsonb(r["components"]), r["reason_text"], r["recipe_matches"],
                     r["model_version"], scored_at, r["uses_sample_data"]))
    with conn.cursor() as cur:
        for i in range(0, len(rows), BATCH):
            cur.executemany(
                "insert into scores (apn, score, components, reason_text, recipe_matches, model_version, "
                "scored_at, uses_sample_data) values (%s,%s,%s,%s,%s,%s,%s,%s)", rows[i:i + BATCH])
    conn.commit()
    summary["scored"] = len(rows)
    summary["scored_at"] = scored_at
    return summary


# ---------------------------------------------------------------------------------------
# land-use profile
# ---------------------------------------------------------------------------------------
def _unit_evidence(parcels_csv: Path | None, apns: set[str]) -> dict[str, dict]:
    """Per land-use code: unit-count evidence (UNITQTY) from the assessor file, if it is on disk,
    limited to parcels in the territory."""
    if parcels_csv is None or not Path(parcels_csv).exists():
        return {}
    import pandas as pd

    df = pd.read_csv(parcels_csv, dtype=str, usecols=["APN", "ASR_LANDUSE", "UNITQTY"])
    df = df[df.APN.isin(apns)].copy()
    df["u"] = pd.to_numeric(df.UNITQTY, errors="coerce")
    out = {}
    for code, g in df.groupby("ASR_LANDUSE"):
        u = g["u"].dropna()
        out[str(code)] = {"med": u.median() if len(u) else "", "min": u.min() if len(u) else "",
                          "max": u.max() if len(u) else ""}
    return out


def latest_parcels_csv() -> Path | None:
    from territory.net import DATA_DIR

    files = sorted((DATA_DIR / "raw" / "parcels").glob("*/Parcels.csv"))
    return files[-1] if files else None


def write_land_use_profile(conn, cfg, report_dir: Path | None = None, parcels_csv: Path | None = None) -> Path:
    """sources/reports/land_use_profile.csv: every distinct parcels.land_use in the territory."""
    codes = set(cfg["residential_codes"])
    areas = sorted(r[0] for r in conn.execute(
        "select distinct planning_area from parcels where planning_area is not null"))
    rows = conn.execute(
        "select coalesce(land_use,'(blank)'), count(*), "
        "count(*) filter (where zoning like 'RS%%'), count(*) filter (where zoning like 'RM%%'), "
        "count(*) filter (where zoning like 'C%%'), count(*) filter (where zoning is null), "
        "percentile_cont(0.5) within group (order by lot_sqft) from parcels group by 1 "
        "order by 2 desc, 1").fetchall()
    per_area = defaultdict(dict)
    for lu, area, n in conn.execute(
            "select coalesce(land_use,'(blank)'), planning_area, count(*) from parcels group by 1,2"):
        per_area[lu][area] = n
    all_apns = {r[0] for r in conn.execute("select apn from parcels")}
    units = _unit_evidence(parcels_csv if parcels_csv is not None else latest_parcels_csv(), all_apns)
    d = report_dir or REPORT_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / "land_use_profile.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["land_use", "parcels", *[f"parcels_{a.lower().replace(' ', '_')}" for a in areas],
                    "zoned_rs", "zoned_rm", "zoned_commercial", "no_zoning", "median_lot_sqft",
                    "units_median", "units_min", "units_max", "scored_as_residential", "note"])
        for lu, n, rs, rm, com, nz, med_lot in rows:
            u = units.get(lu, {})
            note = cfg["residential_land_use"].get(lu, "") if lu in codes else ""
            w.writerow([lu, n, *[per_area[lu].get(a, 0) for a in areas], rs, rm, com, nz,
                        round(float(med_lot), 0) if med_lot is not None else "",
                        u.get("med", ""), u.get("min", ""), u.get("max", ""),
                        "yes" if lu in codes else "no", note])
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.score")
    ap.add_argument("--client", required=True)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="default: today")
    ap.add_argument("--profile-land-use", action="store_true")
    args = ap.parse_args(argv)
    load_client(args.client)
    cfg = load_scoring_config()
    with connect() as conn:
        if args.profile_land_use:
            print(write_land_use_profile(conn, cfg))
            return 0
        s = run_score(conn, cfg, args.as_of or date.today())
    print(f"model {s['model_version']} as of {s['as_of']}: scored {s['scored']} of "
          f"{s['residential_parcels']} residential parcels ({s['non_residential_parcels']} non-residential "
          f"not scored); suppressed {dict(s['suppressed'])}; fire data loaded: {bool(s['loaded_data'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
