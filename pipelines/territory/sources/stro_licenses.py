"""City of San Diego short-term rental (STRO) licenses.

Privacy (CLAUDE.md, D3): only license id, tier, status and location are stored.
Host name, local-contact name/phone and every other column are dropped on read
by an explicit whitelist, before anything reaches raw_records or signals.

Signals
- stro_license_active   snapshot, signal_date = run date, one per license present.
- stro_license_removed  a license present in the previous successful run and
  absent now. The first run is a baseline and produces no removals.
Matching: point-in-polygon on latitude/longitude (match_method = spatial).
"""
from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

from territory.net import download
from territory.sources.base import (
    CONF_SPATIAL, CONF_SPATIAL_AMBIGUOUS, NO_MATCH, Match, RawRecord, SignalCandidate,
    SourceAdapter,
)

URL = "https://seshat.datasd.org/stro_licenses/stro_licenses_datasd.csv"

# Whitelist: the ONLY source columns that may be read into memory.
KEEP_COLUMNS = ["license_id", "address", "zip", "tier", "community_planning_area",
                "longitude", "latitude"]


def _street_key(address: str | None) -> str | None:
    m = re.match(r"^\s*(\d+)\s+([A-Za-z0-9 ]+?)\s*(,|$)", address or "")
    return f"{m.group(1)} {m.group(2).upper()}" if m else None


class StroLicensesAdapter(SourceAdapter):
    source_key = "stro_licenses"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._match: dict[str, Match] = {}
        self._current_ids: set[str] = set()
        self._wanted = {n.upper() for n in ctx.client.territory.planning_areas}

    # ---- fetch -------------------------------------------------------------
    def _path(self):
        p = self.ctx.local_files.get("stro_licenses")
        return p if p else download(self.source_key, URL, run_date=self.ctx.run_date)

    def fetch(self, run_id: str) -> Iterable[RawRecord]:
        df = pd.read_csv(self._path(), dtype=str, usecols=lambda c: c in KEEP_COLUMNS)
        idx = self.ctx.parcels
        out_of_territory = no_location_outside = 0
        seen: set[str] = set()
        for r in df.to_dict("records"):
            lic = (r.get("license_id") or "").strip()
            if not lic or lic in seen:
                continue
            lat, lon = pd.to_numeric(r.get("latitude"), errors="coerce"), pd.to_numeric(
                r.get("longitude"), errors="coerce")
            has_xy = pd.notna(lat) and pd.notna(lon)
            if has_xy:
                in_scope = idx.in_territory(float(lon), float(lat))
            else:  # no coordinates: fall back to the file's planning-area label
                in_scope = (r.get("community_planning_area") or "").strip().upper() in self._wanted
            if not in_scope:
                out_of_territory += 1
                continue
            seen.add(lic)
            payload = {
                "license_id": lic,
                "tier": (r.get("tier") or "").strip() or None,
                "status": "active",   # the City file lists active licenses only
                "address": (r.get("address") or "").strip() or None,
                "zip": (r.get("zip") or "").strip() or None,
                "community_planning_area": (r.get("community_planning_area") or "").strip().title() or None,
                "latitude": float(lat) if has_xy else None,
                "longitude": float(lon) if has_xy else None,
            }
            self._current_ids.add(lic)
            yield RawRecord(self.source_key, lic, payload)
        self.notes["rows in City file"] = len(df)
        self.notes["excluded: outside territory"] = out_of_territory

    # ---- match -------------------------------------------------------------
    def match(self, raw: RawRecord) -> Match:
        cached = self._match.get(raw.source_record_id)
        if cached:
            return cached
        p = raw.payload
        res = NO_MATCH
        if p.get("latitude") is not None:
            hits = self.ctx.parcels.containing(p["longitude"], p["latitude"])
            if len(hits) == 1:
                res = Match(hits[0], "spatial", CONF_SPATIAL)
            elif len(hits) > 1:
                key = _street_key(p.get("address"))
                same = [a for a in hits if key and key == _street_key(
                    self.ctx.parcels.info[a]["situs_address"])]
                pick = same[0] if len(same) == 1 else hits[0]
                res = Match(pick, "spatial", CONF_SPATIAL_AMBIGUOUS,
                            note=f"{len(hits)} stacked parcels contain the point")
        self._match[raw.source_record_id] = res
        return res

    def safe_view(self, raw: RawRecord) -> dict:
        p = raw.payload
        return {"license_id": p["license_id"], "tier": p["tier"], "address": p["address"],
                "lat": p["latitude"], "lon": p["longitude"]}

    # ---- normalize ---------------------------------------------------------
    def normalize(self, raw: RawRecord) -> Iterable[SignalCandidate]:
        m = self.match(raw)
        if not m.apn:
            return
        p = raw.payload
        yield SignalCandidate(
            signal_type="stro_license_active", signal_group="stro",
            source_key=self.source_key, source_record_id=raw.source_record_id,
            confidence=m.confidence, match_method=m.method, apn=m.apn,
            signal_date=self.ctx.run_date,
            details={"license_id": p["license_id"], "tier": p["tier"], "status": "active",
                     "address": p["address"], "zip": p["zip"],
                     "community_planning_area": p["community_planning_area"],
                     "candidate_parcels_note": m.note or None})

    def finalize(self) -> Iterable[SignalCandidate]:
        conn = self.ctx.conn
        prev = conn.execute(
            "select id, started_at::date from source_runs where source_key=%s and status='success' "
            "and id<>%s order by started_at desc limit 1", (self.source_key, self.ctx.run_id)).fetchone()
        if not prev:
            self.notes["baseline"] = "first run: baseline only, no stro_license_removed signals"
            return
        prev_id, prev_date = prev
        old = conn.execute(
            "select source_record_id, apn, confidence, match_method from signals "
            "where run_id=%s and signal_type='stro_license_active'", (prev_id,)).fetchall()
        gone = [o for o in old if o[0] not in self._current_ids]
        self.notes["previous run"] = f"{prev_id} ({prev_date})"
        self.notes["licenses removed since previous run"] = len(gone)
        for lic, apn, conf, method in gone:
            yield SignalCandidate(
                signal_type="stro_license_removed", signal_group="stro",
                source_key=self.source_key, source_record_id=lic, confidence=float(conf),
                match_method=method, apn=apn, signal_date=self.ctx.run_date,
                details={"license_id": lic, "last_seen_run_id": str(prev_id),
                         "last_seen_date": str(prev_date)})
