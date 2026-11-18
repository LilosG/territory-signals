"""City of San Diego development permit approvals (all four sets).

Sets (https://seshat.datasd.org/development_permits/): active (full file),
issued / closed / created (per-year files for 2025 and 2026). One approval can
appear in several sets; it is stored once per run, from the most advanced set
(closed > issued > active > created), with every set it appeared in listed.

Scope and matching. Only approvals that belong to the client's territory are
stored. Order of matching:
  1. GIS_APN found in the parcel table                -> match_method apn
  2. otherwise GIS_LATITUDE/LONGITUDE inside a parcel   -> spatial
  3. otherwise the street address equals one parcel's   -> address
Rows with a blank/unknown APN and no usable location cannot be placed; they are
counted in the match report, not stored.

Signals: permit_approved (signal_group from config/permit_signal_map.yaml, by
exact APPROVAL_TYPE) and permit_stalled (issued, APPROVAL_EXPIRE_DATE passed, no
APPROVAL_CLOSE_DATE and not in a terminal status).

Privacy: APPROVAL_PERMIT_HOLDER (a person/business name) is dropped on read.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
import shapely
import yaml

from territory.net import download
from territory.reports import REPORT_DIR
from territory.sources.base import (
    CONF_ADDRESS, CONF_ADDRESS_AMBIGUOUS, CONF_APN, CONF_SPATIAL_AMBIGUOUS,
    CONF_SPATIAL_FALLBACK, NO_MATCH, Match, RawRecord, SignalCandidate, SourceAdapter,
)

BASE = "https://seshat.datasd.org/development_permits/"
FILES = [
    "approvals_active_datasd.csv",
    "approvals_issued_2025_datasd.csv", "approvals_issued_2026_datasd.csv",
    "approvals_closed_2025_datasd.csv", "approvals_closed_2026_datasd.csv",
    "approvals_created_2025_datasd.csv", "approvals_created_2026_datasd.csv",
]
SET_RANK = {"created": 1, "active": 2, "issued": 3, "closed": 4}
MAP_PATH = Path(__file__).resolve().parents[3] / "config" / "permit_signal_map.yaml"
SIGNAL_GROUPS = ["pre_sale_prep", "remodel_addition", "adu", "demolition_lot_split",
                 "solar_energy", "other"]
DROP_COLUMNS = {"APPROVAL_PERMIT_HOLDER"}
TERMINAL_STATUS = {"closed", "final closed", "finaled", "completed", "cancelled",
                   "cancelled utilization not met", "void", "withdrawn"}
CHUNK = 200_000


def set_name(filename: str) -> str:
    for s in SET_RANK:
        if f"approvals_{s}_" in filename:
            return s
    raise ValueError(f"cannot tell which permit set {filename} belongs to")


def _date(v) -> date | None:
    d = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(d) else d.date()


def clean_apn(v) -> str | None:
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s if len(s) == 10 else None


class DevPermitsAdapter(SourceAdapter):
    source_key = "dev_permits"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._rows: dict[str, dict] = {}     # approval id -> {rank, row, sets}
        self._match: dict[str, Match] = {}
        self._map: dict[str, str] = {}
        self.unmapped: Counter = Counter()

    # ---- files ---------------------------------------------------------------
    def _paths(self) -> list[Path]:
        given = self.ctx.local_files.get("dev_permits")
        if given:
            return [Path(p) for p in given]
        return [download(self.source_key, BASE + f, run_date=self.ctx.run_date) for f in FILES]

    # ---- scan + profile (before any mapping or signals) ------------------------
    def prepare(self) -> None:
        self._scan()
        self.write_profile()
        self._load_map()

    def _scan(self) -> None:
        idx = self.ctx.parcels
        apn_set = set(idx.apns)
        out_territory = unlocatable = 0
        total = 0
        for path in self._paths():
            sname = set_name(path.name)
            rank = SET_RANK[sname]
            header = pd.read_csv(path, nrows=0).columns
            cols = [c for c in header if c not in DROP_COLUMNS]
            for chunk in pd.read_csv(path, dtype=str, usecols=cols, chunksize=CHUNK):
                total += len(chunk)
                apn = chunk["GIS_APN"].map(clean_apn)
                lat = pd.to_numeric(chunk["GIS_LATITUDE"], errors="coerce")
                lon = pd.to_numeric(chunk["GIS_LONGITUDE"], errors="coerce")
                has_xy = lat.notna() & lon.notna() & (lat != 0) & (lon != 0)
                in_terr = pd.Series(False, index=chunk.index)
                if has_xy.any() and idx.territory is not None:
                    in_terr[has_xy] = shapely.contains_xy(
                        idx.territory, lon[has_xy].to_numpy(), lat[has_xy].to_numpy())
                is_apn = apn.isin(apn_set)
                need = is_apn | in_terr | ~has_xy
                out_territory += int((~need).sum())
                for i in chunk.index[need]:
                    row = chunk.loc[i]
                    a = apn[i] if isinstance(apn[i], str) else None
                    m = self._match_row(row, a, lat[i], lon[i], bool(has_xy[i]), bool(in_terr[i]))
                    if m is None:           # cannot be placed in the territory
                        if a is None:
                            unlocatable += 1
                        else:
                            out_territory += 1
                        continue
                    aid = (row.get("APPROVAL_ID") or "").strip()
                    if not aid:
                        continue
                    rec = {k: v for k, v in row.items() if isinstance(v, str) and v.strip() != ""}
                    cur = self._rows.get(aid)
                    if cur is None:
                        self._rows[aid] = {"rank": rank, "row": rec, "sets": {sname}, "match": m}
                    else:
                        cur["sets"].add(sname)
                        if rank > cur["rank"]:
                            cur.update(rank=rank, row=rec, match=m)
        self.notes["rows read from all permit files"] = total
        self.notes["excluded: outside territory"] = out_territory
        self.notes["excluded: blank/unknown APN and no usable location"] = unlocatable
        self.notes["distinct approvals in territory scope"] = len(self._rows)

    def _match_row(self, row, apn, lat, lon, has_xy, in_terr):
        """Returns a Match (apn None = in territory but unplaceable) or None (not ours)."""
        idx = self.ctx.parcels
        if apn and apn in idx:
            return Match(apn, "apn", CONF_APN)
        if has_xy and in_terr:
            hits = idx.containing(float(lon), float(lat))
            if len(hits) == 1:
                return Match(hits[0], "spatial", CONF_SPATIAL_FALLBACK, "apn blank or not a territory parcel")
            if len(hits) > 1:
                addr = idx.at_address(row.get("GIS_ADDRESS"))
                pick = [a for a in hits if a in addr]
                return Match(pick[0] if len(pick) == 1 else hits[0], "spatial",
                             CONF_SPATIAL_AMBIGUOUS, f"{len(hits)} stacked parcels contain the point")
        addr = idx.at_address(row.get("GIS_ADDRESS"))
        if addr and (not has_xy or in_terr):
            conf = CONF_ADDRESS if len(addr) == 1 else CONF_ADDRESS_AMBIGUOUS
            return Match(addr[0], "address", conf, f"{len(addr)} parcels share the address")
        if has_xy and in_terr:
            return NO_MATCH        # inside the territory but no parcel found
        return None

    def write_profile(self) -> Path:
        """pipelines/territory/sources/reports/permit_type_profile.csv: every distinct
        APPROVAL_TYPE and PROJECT_TYPE with counts inside the territory."""
        counts: dict[tuple[str, str], list[int]] = {}
        for rec in self._rows.values():
            row = rec["row"]
            issued = 1 if row.get("APPROVAL_ISSUE_DATE") else 0
            for field in ("APPROVAL_TYPE", "PROJECT_TYPE"):
                v = row.get(field, "(blank)")
                c = counts.setdefault((field, v), [0, 0])
                c[0] += 1
                c[1] += issued
        d = self.ctx.report_dir or REPORT_DIR
        d.mkdir(parents=True, exist_ok=True)
        path = d / "permit_type_profile.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["field", "value", "approvals_in_territory", "issued_approvals_in_territory"])
            for (field, v), (n, iss) in sorted(counts.items(), key=lambda x: (x[0][0], -x[1][0], x[0][1])):
                w.writerow([field, v, n, iss])
        return path

    def _load_map(self) -> None:
        path = Path(self.ctx.local_files.get("permit_signal_map") or MAP_PATH)
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; review permit_type_profile.csv and create it")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        mapping = data.get("approval_types") or {}
        bad = {k: v for k, v in mapping.items() if v not in SIGNAL_GROUPS}
        if bad:
            raise ValueError(f"permit_signal_map.yaml has unknown signal groups: {bad}")
        self._map = mapping
        self.notes["permit_signal_map status"] = data.get("status")

    # ---- fetch / match / normalize ---------------------------------------------
    def fetch(self, run_id: str) -> Iterable[RawRecord]:
        for aid in sorted(self._rows):
            rec = self._rows[aid]
            payload = dict(rec["row"])
            payload["_sets"] = sorted(rec["sets"])
            self._match[aid] = rec["match"]
            yield RawRecord(self.source_key, aid, payload)

    def match(self, raw: RawRecord) -> Match:
        return self._match.get(raw.source_record_id, NO_MATCH)

    def safe_view(self, raw: RawRecord) -> dict:
        p = raw.payload
        return {"approval_id": raw.source_record_id, "approval_type": p.get("APPROVAL_TYPE"),
                "address": p.get("GIS_ADDRESS"), "apn": p.get("GIS_APN"),
                "lat": p.get("GIS_LATITUDE"), "lon": p.get("GIS_LONGITUDE")}

    def normalize(self, raw: RawRecord) -> Iterable[SignalCandidate]:
        m = self.match(raw)
        if not m.apn:
            return
        p = raw.payload
        atype = p.get("APPROVAL_TYPE", "")
        group = self._map.get(atype)
        if group is None:
            group = "other"
            self.unmapped[atype or "(blank)"] += 1
            self.notes["APPROVAL_TYPE values not in the map (-> other)"] = dict(self.unmapped)
        issue, expire, close = (_date(p.get("APPROVAL_ISSUE_DATE")), _date(p.get("APPROVAL_EXPIRE_DATE")),
                                _date(p.get("APPROVAL_CLOSE_DATE")))
        base = {
            "approval_id": raw.source_record_id, "approval_type": atype or None,
            "approval_status": p.get("APPROVAL_STATUS"), "project_type": p.get("PROJECT_TYPE"),
            "project_id": p.get("PROJECT_ID"), "job_description": p.get("JOB_BC_CODE_DESCRIPTION"),
            "scope": (p.get("APPROVAL_SCOPE") or "")[:500] or None,
            "valuation": p.get("APPROVAL_VALUATION"), "adu_total": p.get("APPROVAL_ADU_TOTAL"),
            "du_net_change": p.get("APPROVAL_DU_NET_CHANGE"),
            "floor_area": p.get("APPROVAL_FLOOR_AREA"),
            "issue_date": str(issue) if issue else None, "expire_date": str(expire) if expire else None,
            "close_date": str(close) if close else None, "sets": p.get("_sets"),
            "match_note": m.note or None,
        }
        if issue:
            yield SignalCandidate("permit_approved", group, self.source_key, raw.source_record_id,
                                  m.confidence, m.method, m.apn, issue, details=base)
        status = (p.get("APPROVAL_STATUS") or "").strip().lower()
        if issue and expire and expire < self.ctx.run_date and close is None \
                and status not in TERMINAL_STATUS:
            yield SignalCandidate(
                "permit_stalled", group, self.source_key, raw.source_record_id, m.confidence,
                m.method, m.apn, expire,
                details={**base, "days_past_expiry": (self.ctx.run_date - expire).days})


def _profile_main() -> None:  # python -m territory.sources.dev_permits --profile
    from territory.config import load_client
    from territory.db import connect
    from territory.sources.base import RunContext

    with connect() as conn:
        ctx = RunContext(conn=conn, run_id="profile", run_date=date.today(),
                         client=load_client("kaiser-team"))
        a = DevPermitsAdapter(ctx)
        a._scan()
        print(a.write_profile())
        for k, v in a.notes.items():
            print(f"{k}: {v}")


if __name__ == "__main__" and "--profile" in sys.argv:
    _profile_main()
