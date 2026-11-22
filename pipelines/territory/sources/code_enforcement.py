"""City of San Diego code enforcement violations (Development Services).

Public CSV: https://seshat.datasd.org/code_enforcement_violations/code_enf_past_3_yr_datasd.csv
(Dataset page: https://data.sandiego.gov/datasets/code-enforcement-violations/.) The published file is a
historical extract; the adapter is written for the same fields a current extract uses.

Matching: the source APN when it is a territory parcel (match_method = apn), otherwise the record's
latitude/longitude point inside a parcel polygon (match_method = spatial). Records outside the territory
are counted in the match report, not stored.

Signals:
  code_violation_open   (signal_group distress)       a case with no close date, dated from its open date
  code_violation_closed (signal_group pre_sale_prep)  a case closed within the last 180 days, dated from its close date

Privacy: investigator name, phone and email are dropped on read, and the free-text description is cut at
the source's "[Addr: ... Owner: ...]" bracket and at reassignment notes, so no personal contact fields or
owner names are stored.
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Iterable

from territory.net import DATA_DIR, download
from territory.sources.base import (
    CONF_APN, CONF_SPATIAL_AMBIGUOUS, CONF_SPATIAL_FALLBACK, NO_MATCH, AwaitingManualDownload,
    Match, RawRecord, SignalCandidate, SourceAdapter,
)

URL = "https://seshat.datasd.org/code_enforcement_violations/code_enf_past_3_yr_datasd.csv"
CLOSED_WINDOW_DAYS = 180
DROP_FIELDS = {
    "investigator_name", "investigator_phone_number", "investigator_email_address",
    "investigator_active", "close_note", "last_action", "date_last_action_due", "remedy_msg",
}
KEEP_FIELDS = (
    "case_id", "apn", "address_street", "case_source", "description", "date_open", "date_closed",
    "close_reason", "workgroup", "lat", "lng",
)
_CUT_BRACKET = re.compile(r"\s*\[\s*addr\b.*$", re.IGNORECASE)
_CUT_REASSIGN = re.compile(r"\b(?:reassigned|trans(?:ferred)?)\s+to\b.*$", re.IGNORECASE)


def clean_apn(value: object) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits if len(digits) == 10 else None


def parse_date(value: object) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def clean_description(value: object) -> str:
    """The violation category, without the bracketed owner/address text or reassignment notes."""
    text = _CUT_BRACKET.sub("", str(value or ""))
    text = _CUT_REASSIGN.sub("", text)
    text = re.split(r"\s+-\s+", text, maxsplit=1)[0]
    return " ".join(text.split()).strip(" -")


def _float(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def newest_cached_file() -> Path | None:
    """The newest dated download in data/raw/code_enforcement, else the small packaged fallback."""
    base = DATA_DIR / "raw" / "code_enforcement"
    files = sorted(p for p in base.glob("*/*.csv") if p.is_file()) if base.exists() else []
    if files:
        return files[-1]
    packaged = Path(__file__).resolve().parent / "fixtures" / "code_enforcement_fallback.csv"
    return packaged if packaged.exists() else None


class CodeEnforcementAdapter(SourceAdapter):
    source_key = "code_enforcement"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._match: dict[str, Match] = {}
        self._fallback_note: str | None = None

    # ---- files ---------------------------------------------------------------
    def _path(self) -> Path:
        given = self.ctx.local_files.get("code_enforcement")
        if given:
            return Path(given)
        try:
            path = download(self.source_key, URL, run_date=self.ctx.run_date)
            self.notes["endpoint status"] = "downloaded from data.sandiego.gov"
            return path
        except Exception as exc:  # noqa: BLE001 - offline runs fall back to the last cache
            cached = newest_cached_file()
            if cached is None:
                self.notes["endpoint status"] = "unreachable and no local cache"
                raise AwaitingManualDownload(
                    "code enforcement CSV: remote endpoint unavailable and no cached file") from exc
            self._fallback_note = f"{type(exc).__name__}: {exc}"
            self.notes["endpoint status"] = f"local cache/fixture (remote unavailable: {type(exc).__name__})"
            return cached

    # ---- fetch / match -------------------------------------------------------
    def fetch(self, run_id: str) -> Iterable[RawRecord]:
        idx = self.ctx.parcels
        path = self._path()
        total = outside = unplaceable = 0
        methods = {"apn": 0, "spatial": 0}
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                total += 1
                case_id = str(row.get("case_id") or "").strip()
                if not case_id:
                    continue
                apn = clean_apn(row.get("apn"))
                lat, lon = _float(row.get("lat")), _float(row.get("lng"))
                m = self._match_record(apn, lat, lon)
                if m is None:
                    outside += 1
                    continue
                if not m.apn:
                    unplaceable += 1
                    continue
                self._match[case_id] = m
                methods[m.method or "apn"] += 1
                payload = {k: row.get(k) for k in KEEP_FIELDS if k not in DROP_FIELDS}
                payload["apn"] = apn
                payload["description"] = clean_description(row.get("description"))
                payload["lat"], payload["lng"] = lat, lon
                yield RawRecord(self.source_key, case_id, payload)
        self.notes["rows read"] = total
        self.notes["excluded: outside territory"] = outside
        self.notes["excluded: in territory but no parcel found"] = unplaceable
        self.notes["matched by"] = {k: v for k, v in methods.items() if v}
        if self._fallback_note:
            self.notes["fallback reason"] = self._fallback_note

    def _match_record(self, apn: str | None, lat: float | None, lon: float | None) -> Match | None:
        """Match, NO_MATCH (ours but unplaceable) or None (not a territory record)."""
        idx = self.ctx.parcels
        if apn and apn in idx:
            return Match(apn, "apn", CONF_APN)
        if lat is not None and lon is not None and idx.in_territory(lon, lat):
            hits = idx.containing(lon, lat)
            if len(hits) == 1:
                return Match(hits[0], "spatial", CONF_SPATIAL_FALLBACK, "APN blank or not a territory parcel")
            if len(hits) > 1:
                return Match(hits[0], "spatial", CONF_SPATIAL_AMBIGUOUS,
                             f"{len(hits)} stacked parcels contain the point")
            return NO_MATCH
        return None

    def match(self, raw: RawRecord) -> Match:
        return self._match.get(raw.source_record_id, NO_MATCH)

    def safe_view(self, raw: RawRecord) -> dict:
        p = raw.payload
        return {"case_id": raw.source_record_id, "apn": p.get("apn"), "address": p.get("address_street"),
                "lat": p.get("lat"), "lng": p.get("lng"), "date_open": p.get("date_open"),
                "date_closed": p.get("date_closed")}

    def normalize(self, raw: RawRecord) -> Iterable[SignalCandidate]:
        m = self.match(raw)
        if not m.apn:
            return
        p = raw.payload
        opened = parse_date(p.get("date_open"))
        closed = parse_date(p.get("date_closed"))
        details = {
            "case_id": raw.source_record_id,
            "violation_category": p.get("description") or None,
            "open_date": str(opened) if opened else None,
            "close_date": str(closed) if closed else None,
            "status": "closed" if closed else "open",
            "case_source": p.get("case_source") or None,
            "workgroup": p.get("workgroup") or None,
        }
        if closed is None:
            if opened is None:
                return
            yield SignalCandidate(
                "code_violation_open", "distress", self.source_key, raw.source_record_id,
                m.confidence, m.method, m.apn, opened, details=details)
            return
        if (self.ctx.run_date - closed).days <= CLOSED_WINDOW_DAYS:
            yield SignalCandidate(
                "code_violation_closed", "pre_sale_prep", self.source_key, raw.source_record_id,
                m.confidence, m.method, m.apn, closed, details=details)
