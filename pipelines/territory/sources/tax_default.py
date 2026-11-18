"""San Diego County Treasurer-Tax Collector: Notice of Impending Power to Sell
Tax-Defaulted Property (annual list, PDF).

Parsed with pdfplumber (each page is cropped into its two columns first, because
the notice prints two records side by side). Matching is by APN
(match_method = apn). The list is countywide; only parcels in the territory are
stored. Names are not stored: only whether the assessee line reads as an estate
("EST OF") or a trust, which is a possible inheritance/transition signal.

Signal: tax_default, signal_date = the date the parcel becomes subject to the
power to sell (read from the notice text).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pdfplumber

from territory.net import download
from territory.sources.base import (
    CONF_APN, NO_MATCH, Match, RawRecord, SignalCandidate, SourceAdapter,
)

URL = ("https://www.sdttc.com/content/dam/ttc/docs/taxcollection/"
       "Notice-of-Impending-Power-to-Sell-Tax-Defaulted-Property-June-5-12-19-2026.pdf")
REC = re.compile(r"(?P<apn>\d{3}-\d{3}-\d{2}-\d{2})\s+(?P<body>.*?)\s*\$(?P<amt>[\d,]+\.\d{2})")
DEFAULTED = re.compile(r"Property tax-defaulted on (?P<d>[A-Za-z]+ \d{1,2}, \d{4})")
POWER = re.compile(r"\bto sell on (?P<d>[A-Za-z]+ \d{1,2}, \d{4})")


def _d(text: str) -> date:
    return datetime.strptime(text, "%B %d, %Y").date()


def page_lines(pdf) -> Iterable[str]:
    for page in pdf.pages:
        mid = page.width / 2
        for box in ((0, 0, mid, page.height), (mid, 0, page.width, page.height)):
            yield from (page.crop(box).extract_text() or "").splitlines()


def split_body(body: str) -> tuple[str, str | None]:
    """body = '<assessee name> <5+ digit house number><street...>' -> (name, address)."""
    m = re.search(r"(?:^|\s)(\d{5}\S*.*)$", body)
    if not m:
        return body.strip(), None
    name, addr = body[:m.start(1)].strip(), m.group(1).strip()
    num = re.match(r"(\d+)(.*)", addr)
    digits = num.group(1).lstrip("0")
    rest = num.group(2).lstrip("#0123456789 ").strip() if digits == "" else num.group(2).strip()
    return name, (f"{digits} {rest}".strip() if digits else rest) or None


def parse_pdf(path: Path) -> tuple[list[dict], date | None]:
    records: list[dict] = []
    defaulted: date | None = None
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page_lines(pdf))
        full = "\n".join((p.extract_text() or "") for p in pdf.pages[:1])
    pm = POWER.search(full)
    power_date = _d(pm.group("d")) if pm else None
    for line in text.splitlines():
        dm = DEFAULTED.search(line)
        if dm:
            defaulted = _d(dm.group("d").replace(" ,", ","))
        for m in REC.finditer(line):
            name, addr = split_body(m.group("body"))
            up = name.upper()
            records.append({
                "apn": m.group("apn").replace("-", ""),
                "tax_defaulted_on": str(defaulted) if defaulted else None,
                "situs_text": addr,
                "amount_to_redeem": float(m.group("amt").replace(",", "")),
                "assessee_estate": bool(re.search(r"\bEST(ATE)? OF\b|\bESTATE\b", up)),
                "assessee_trust": bool(re.search(r"\bTRUST\b|\bTR\b", up)),
            })
    return records, power_date


class TaxDefaultAdapter(SourceAdapter):
    source_key = "tax_default"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._power_date: date | None = None

    def fetch(self, run_id: str) -> Iterable[RawRecord]:
        path = self.ctx.local_files.get("tax_default") or download(
            self.source_key, URL, run_date=self.ctx.run_date)
        records, self._power_date = parse_pdf(Path(path))
        idx = self.ctx.parcels
        seen: set[str] = set()
        outside = dups = 0
        for r in records:
            if r["apn"] in seen:
                dups += 1
                continue
            seen.add(r["apn"])
            if r["apn"] not in idx:
                outside += 1
                continue
            r["power_to_sell_date"] = str(self._power_date) if self._power_date else None
            yield RawRecord(self.source_key, r["apn"], r)
        self.notes["parcels on the countywide list"] = len(seen)
        self.notes["excluded: not a territory parcel"] = outside
        self.notes["duplicate APN lines skipped"] = dups

    def match(self, raw: RawRecord) -> Match:
        return Match(raw.source_record_id, "apn", CONF_APN) if raw.source_record_id in self.ctx.parcels \
            else NO_MATCH

    def safe_view(self, raw: RawRecord) -> dict:
        return {"apn": raw.source_record_id, "situs_text": raw.payload.get("situs_text")}

    def normalize(self, raw: RawRecord) -> Iterable[SignalCandidate]:
        m = self.match(raw)
        if not m.apn:
            return
        p = raw.payload
        when = date.fromisoformat(p["power_to_sell_date"]) if p.get("power_to_sell_date") else None
        yield SignalCandidate(
            "tax_default", "distress", self.source_key, raw.source_record_id, m.confidence,
            m.method, m.apn, when,
            details={"tax_defaulted_on": p["tax_defaulted_on"], "amount_to_redeem": p["amount_to_redeem"],
                     "situs_text": p["situs_text"], "assessee_estate": p["assessee_estate"],
                     "assessee_trust": p["assessee_trust"],
                     "list": "Notice of Impending Power to Sell, June 2026"})
