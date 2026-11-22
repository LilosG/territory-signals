"""ATTOM Property API owner/recorder provider with a permanent response cache and a trial quota governor.

    from territory.owner_data.attom import AttomOwnerProvider

The provider is deliberately split in two parts:

* pure parsers (``parse_owner``, ``parse_recorder_documents``, ``parse_sale_records``) that turn an ATTOM
  expanded profile / expanded sales history payload into the database shapes; and
* a thin client that caches every raw JSON response permanently in ``raw_records`` and records every API
  call attempt in ``api_usage_log`` before allowing the next one.

A parcel is therefore never fetched twice unless ``refresh_days`` is set and the cache entry is older than
that. The daily budget (``max_calls``, default 450) is read from ``api_usage_log``; the provider refuses
the call that would cross it. Tests inject a ``fetcher`` so the suite makes zero live HTTP calls.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

from territory.scoring_engine import load_recorder_signals, load_transfer_types, norm_doc_type

from .base import NotConfiguredError, OwnerDataProvider, OwnerRecord, SaleRecord

BASE_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"
PROFILE_ENDPOINT = "expandedprofile"
HISTORY_ENDPOINT = "expandedhistory"
FIPS_SAN_DIEGO = "06073"
DEFAULT_MAX_CALLS = 450
SOURCE_KEY = "attom"

Fetcher = Callable[[str, str, Optional[str]], Mapping[str, Any]]

# Personal identifiers that must never reach the permanent cache (CLAUDE.md privacy rules).
_SENSITIVE_KEY = re.compile(r"(phone|ssn|social.?security|email|cell|fax)", re.I)


def redact_payload(obj: Any) -> Any:
    """Recursively replace phone / SSN / email fields before a raw response is stored.

    The cached response keeps every property, owner, value, mortgage and recorder field the pipeline uses;
    only personal contact identifiers are blanked. The raw ATTOM payload is never written to disk with them.
    """
    if isinstance(obj, Mapping):
        return {k: ("[redacted]" if _SENSITIVE_KEY.search(str(k)) else redact_payload(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_payload(v) for v in obj]
    return obj


class QuotaExceededError(RuntimeError):
    """Raised when the next ATTOM call would exceed the daily --max-calls budget."""


# ---------------------------------------------------------------------------------------
# small parsing helpers
# ---------------------------------------------------------------------------------------
def _first(payload: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return None
    props = payload.get("property")
    if isinstance(props, list) and props and isinstance(props[0], Mapping):
        return dict(props[0])
    return None


def _as_dict(v: Any) -> dict[str, Any]:
    return dict(v) if isinstance(v, Mapping) else {}


def _num(*values: Any) -> Optional[float]:
    for v in values:
        if v is None or v == "":
            continue
        try:
            f = float(str(v).replace(",", "").replace("$", "").strip())
            if f == f and f not in (float("inf"), float("-inf")):
                return f
        except (TypeError, ValueError):
            continue
    return None


def _dig(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _parse_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y%m%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            pass
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _address_line(profile: Mapping[str, Any]) -> str:
    addr = _as_dict(profile.get("address"))
    parts = [addr.get("line1"), addr.get("line2"), addr.get("locality"),
             addr.get("countrySubd"), addr.get("postal1")]
    return ", ".join(str(p).strip() for p in parts if p and str(p).strip())


def _mailing(owner: Mapping[str, Any]) -> tuple[str, Optional[str], Optional[str]]:
    """(one-line mailing address, state, zip) from either ATTOM mailing shape."""
    raw = owner.get("mailingaddressunparsed") or owner.get("mailingAddressUnparsed")
    mail = _as_dict(owner.get("mailingaddress") or owner.get("mailingAddress"))
    if mail:
        parts = [mail.get("line1"), mail.get("line2"), mail.get("locality"),
                 mail.get("countrySubd"), mail.get("postal1")]
        text = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
        return text or str(raw or ""), _s(mail.get("countrySubd")), _s(mail.get("postal1"))
    text = str(raw or "").strip()
    m = re.search(r",\s*([A-Za-z]{2})\s+(\d{5})(?:-\d{4})?\s*$", text)
    return text, (m.group(1).upper() if m else None), (m.group(2) if m else None)


def _s(v: Any) -> Optional[str]:
    s = str(v).strip() if v is not None else ""
    return s or None


def _norm_addr(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).strip()


def _owner_name(owner: Mapping[str, Any]) -> Optional[str]:
    for key in ("owner1", "owner2", "owner3", "owner4"):
        name = _s(_dig(owner, key, "fullname"))
        if name:
            return name
    return _s(owner.get("fullname") or owner.get("name"))


def parse_owner(apn: str, profile_payload: Optional[Mapping[str, Any]],
                history_payload: Optional[Mapping[str, Any]] = None,
                as_of: Optional[date] = None) -> Optional[OwnerRecord]:
    """Turn one expanded profile (plus optional recorder history) into an OwnerRecord.

    ATTOM payloads with no property are not an owner row (None). The returned fields are the only ones
    stored: no phone numbers, SSNs, or other personal identifiers are read or retained.
    """
    profile = _first(profile_payload)
    if profile is None:
        return None
    assessment = _as_dict(profile.get("assessment"))
    owner = _as_dict(assessment.get("owner"))
    property_addr = _address_line(profile)
    mail_text, mail_state, _mail_zip = _mailing(owner)
    prop_state = _s(_dig(profile, "address", "countrySubd"))
    out_of_state = bool(mail_state and prop_state and mail_state.upper() != prop_state.upper())
    absentee = bool(mail_text) and (out_of_state or _norm_addr(mail_text) != _norm_addr(property_addr))
    owner_occupied = bool(mail_text) and not absentee

    mortgage = _as_dict(profile.get("mortgage"))
    mortgage_amount = _num(mortgage.get("amount"), mortgage.get("mortgageAmount"),
                           _dig(profile, "sale", "mortgageAmount"))
    mortgage_open = mortgage.get("open")
    if mortgage_open is None:
        mortgage_open = bool(mortgage_amount and mortgage_amount > 0)
    mortgage_open = bool(mortgage_open)

    est_value = _num(_dig(profile, "avm", "amount", "value"), _dig(profile, "avm", "amount"),
                     _dig(assessment, "assessed", "assdTtlValue"),
                     _dig(assessment, "market", "marketTotalValue")) or 0.0

    docs = parse_recorder_documents(apn, history_payload)
    conveyances = [d for d in docs if not d.is_distress]
    last_date: Optional[date] = None
    last_price: Optional[float] = None
    if conveyances:
        last = max(conveyances, key=lambda d: (d.document_date, d.doc_type))
        last_date = last.document_date
        last_price = last.amount if not last.is_transfer and last.amount and last.amount > 0 else None
    if last_date is None:
        sale = _as_dict(profile.get("sale"))
        last_date = _parse_date(sale.get("salesearchdate") or sale.get("saleTransDate"))
        last_price = _num(sale.get("saleamt") or sale.get("amount"))

    equity = round(est_value - (mortgage_amount or 0.0 if mortgage_open else 0.0), 2)
    return OwnerRecord(
        apn=apn,
        owner_name=_owner_name(owner) or f"Owner of record {apn}",
        mailing_address=mail_text or "",
        owner_occupied=owner_occupied,
        absentee=absentee,
        out_of_state=out_of_state,
        last_sale_date=last_date,
        last_sale_price=last_price,
        mortgage_open=mortgage_open,
        est_value=float(est_value),
        est_equity=equity,
        provider=SOURCE_KEY,
        is_sample=False,
        as_of=as_of or date.today(),
    )


@dataclass(frozen=True)
class RecorderDocument:
    apn: str
    document_date: date
    doc_type: str
    code: str
    amount: Optional[float]
    kind: str
    label: str
    is_transfer: bool
    is_distress: bool
    signal: Optional[str] = None

    @property
    def normal_type(self) -> str:
        return norm_doc_type(self.doc_type)


def _history_items(history_payload: Optional[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prop = _first(history_payload)
    if prop is None:
        return []
    items = prop.get("salehistory")
    if isinstance(items, list):
        return [dict(x) for x in items if isinstance(x, Mapping)]
    return []


def parse_recorder_documents(apn: str, history_payload: Optional[Mapping[str, Any]],
                             transfer_types: Optional[Mapping[str, Mapping[str, str]]] = None,
                             recorder_signals: Optional[Mapping[str, Mapping[str, str]]] = None,
                             ) -> list[RecorderDocument]:
    """Every dated recorder document in an expanded history, classified as conveyance or distress.

    Returns newest first, deterministically. Unknown document types are conveyances with no transfer flag
    (ordinary deeds), never signals.
    """
    transfers = transfer_types if transfer_types is not None else load_transfer_types()
    distress = recorder_signals if recorder_signals is not None else load_recorder_signals()
    out: list[RecorderDocument] = []
    for item in _history_items(history_payload):
        when = _parse_date(item.get("saleTransDate") or item.get("saleSearchDate") or item.get("documentDate"))
        if when is None:
            continue
        doc_type = str(item.get("documentType") or item.get("documentTypeCode") or "").strip()
        code = str(item.get("documentTypeCode") or "").strip()
        keys = [norm_doc_type(doc_type), norm_doc_type(code)]
        transfer = next((transfers[k] for k in keys if k in transfers), None)
        record = next((distress[k] for k in keys if k in distress), None)
        amount = _num(item.get("saleAmt"), item.get("saleAmount"), item.get("amount"))
        out.append(RecorderDocument(
            apn=apn, document_date=when, doc_type=doc_type or (transfer or record or {}).get("label", ""),
            code=code, amount=amount,
            kind=(transfer or record or {}).get("kind", "sale"),
            label=(transfer or record or {}).get("label", doc_type or "Recorded document"),
            is_transfer=transfer is not None,
            is_distress=record is not None,
            signal=(record or {}).get("signal"),
        ))
    return sorted(out, key=lambda d: (d.document_date, d.doc_type, d.code), reverse=True)


def parse_sale_records(apn: str, history_payload: Optional[Mapping[str, Any]],
                       transfer_types: Optional[Mapping[str, Mapping[str, str]]] = None,
                       ) -> list[SaleRecord]:
    """Actual conveyances for ``sales_history``. Distress recordings never enter that table."""
    out: list[SaleRecord] = []
    for doc in parse_recorder_documents(apn, history_payload, transfer_types=transfer_types):
        if doc.is_distress:
            continue
        out.append(SaleRecord(
            apn=apn, sale_date=doc.document_date,
            sale_price=doc.amount if not doc.is_transfer and doc.amount and doc.amount > 0 else None,
            doc_type=doc.doc_type, provider=SOURCE_KEY, is_sample=False, confidence=1.0,
        ))
    return out


def recorder_signal_candidates(apn: str, docs: Iterable[RecorderDocument]) -> list[dict[str, Any]]:
    """Signals to write for recorder documents: inheritance transfers and distress filings only."""
    out: list[dict[str, Any]] = []
    for doc in docs:
        if doc.is_transfer:
            out.append({"signal_type": "ownership_transfer_inheritance", "signal_group": "life_event",
                        "signal_date": doc.document_date, "doc_type": doc.doc_type,
                        "transfer_kind": doc.kind, "label": doc.label})
        elif doc.is_distress and doc.signal:
            out.append({"signal_type": doc.signal, "signal_group": "distress",
                        "signal_date": doc.document_date, "doc_type": doc.doc_type,
                        "notice_kind": doc.kind, "label": doc.label})
    return out


# ---------------------------------------------------------------------------------------
# provider: cache + quota governor
# ---------------------------------------------------------------------------------------
class AttomOwnerProvider(OwnerDataProvider):
    """ATTOM Property API provider.

    ``conn``/``run_id`` enable the permanent raw-record cache and the daily call ledger. ``fetcher`` replaces
    the HTTP call (tests pass recorded fixtures). Without a key and without a fetcher the provider refuses to
    start, exactly as the Phase 3 skeleton did.
    """

    provider = SOURCE_KEY

    def __init__(self, *, conn: Any = None, run_id: Optional[str] = None, api_key: Optional[str] = None,
                 fetcher: Optional[Fetcher] = None, max_calls: int = DEFAULT_MAX_CALLS,
                 refresh_days: Optional[int] = None, as_of: Optional[date] = None,
                 timeout: float = 30.0) -> None:
        self._api_key = api_key or os.environ.get("ATTOM_API_KEY")
        if not self._api_key and fetcher is None:
            raise NotConfiguredError(
                "ATTOM_API_KEY is not set. Add it to the environment to use the ATTOM provider; "
                "until then use SampleOwnerProvider (owner_data_provider: sample) or hybrid mode."
            )
        self._conn = conn
        self._run_id = run_id
        self._fetcher = fetcher
        self._max_calls = int(max_calls)
        self._refresh_days = refresh_days
        self._as_of = as_of
        self._timeout = timeout
        self.calls_made = 0
        self.cache_hits = 0

    # ---- run / usage bookkeeping --------------------------------------------------------
    def _ensure_run(self) -> Optional[str]:
        if self._run_id is not None:
            return self._run_id
        if self._conn is None:
            return None
        self._run_id = str(self._conn.execute(
            "insert into source_runs (source_key, status) values (%s, 'running') returning id",
            (SOURCE_KEY,)).fetchone()[0])
        return self._run_id

    def close_run(self, status: str = "success", rows_fetched: int = 0, rows_matched: int = 0,
                  rows_unmatched: int = 0) -> None:
        if self._conn is None or self._run_id is None:
            return
        self._conn.execute(
            "update source_runs set status=%s, finished_at=now(), rows_fetched=%s, rows_matched=%s, "
            "rows_unmatched=%s where id=%s",
            (status, rows_fetched, rows_matched, rows_unmatched, self._run_id))

    def _today(self) -> date:
        return self._as_of or date.today()

    def daily_calls(self) -> int:
        if self._conn is None:
            return self.calls_made
        return int(self._conn.execute(
            "select coalesce(sum(request_count), 0) from api_usage_log "
            "where source_key=%s and call_date=%s", (SOURCE_KEY, self._today())).fetchone()[0])

    def _record_usage(self, endpoint: str, apn: str, status: str, http_status: Optional[int]) -> None:
        self.calls_made += 1
        if self._conn is not None:
            self._conn.execute(
                "insert into api_usage_log (call_date, source_key, endpoint, apn, request_count, status, http_status) "
                "values (%s,%s,%s,%s,1,%s,%s)",
                (self._today(), SOURCE_KEY, endpoint, apn, status, http_status))

    def _enforce_quota(self) -> None:
        if self._max_calls is not None and self.daily_calls() >= self._max_calls:
            raise QuotaExceededError(
                f"ATTOM daily call budget reached ({self._max_calls} calls on {self._today()}); "
                "no further API calls will be made today.")

    # ---- cache ---------------------------------------------------------------------------
    @staticmethod
    def _source_record_id(apn: str, endpoint: str, variant: str = "apn") -> str:
        return f"apn:{apn}:{endpoint}:{variant}"

    def _read_cache(self, source_record_id: str) -> Optional[dict[str, Any]]:
        if self._conn is None:
            return None
        row = self._conn.execute(
            "select payload, fetched_at from raw_records where source_key=%s and source_record_id=%s "
            "order by fetched_at desc limit 1", (SOURCE_KEY, source_record_id)).fetchone()
        if row is None:
            return None
        fetched_at = row[1]
        if self._refresh_days is not None:
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - fetched_at > timedelta(days=self._refresh_days):
                return None
        self.cache_hits += 1
        return dict(row[0])

    def _write_cache(self, source_record_id: str, payload: Mapping[str, Any]) -> None:
        if self._conn is None:
            return
        run_id = self._ensure_run()
        if run_id is None:
            return
        from psycopg.types.json import Jsonb

        self._conn.execute(
            "insert into raw_records (source_key, source_record_id, run_id, payload, fetched_at) "
            "values (%s,%s,%s,%s,%s)",
            (SOURCE_KEY, source_record_id, run_id, Jsonb(redact_payload(dict(payload))),
             datetime.now(timezone.utc)))

    # ---- HTTP ----------------------------------------------------------------------------
    def _http(self, endpoint: str, apn: str, address: Optional[str],
              use_address: bool = False) -> tuple[dict[str, Any], int]:
        import requests

        root = BASE_URL.rstrip("/")
        path = "property/expandedprofile" if endpoint == PROFILE_ENDPOINT else "saleshistory/expandedhistory"
        if use_address and address:
            params: dict[str, str] = {"address1": address}
        elif apn:
            params = {"apn": apn, "fips": FIPS_SAN_DIEGO}
        elif address:
            params = {"address1": address}
        else:
            params = {}
        headers = {"apikey": self._api_key or "", "Accept": "application/json"}
        r = requests.get(f"{root}/{path}", params=params, headers=headers, timeout=self._timeout)
        try:
            payload = r.json()
        except ValueError:
            payload = {"status": {"code": r.status_code, "msg": "invalid JSON"}, "property": []}
        return (dict(payload) if isinstance(payload, Mapping) else {"property": []}), r.status_code

    def _request(self, endpoint: str, apn: str, address: Optional[str] = None,
                 variant: str = "apn") -> dict[str, Any]:
        sid = self._source_record_id(apn, endpoint, variant)
        cached = self._read_cache(sid)
        if cached is not None:
            return cached
        self._enforce_quota()
        http_status: Optional[int] = None
        try:
            if self._fetcher is not None:
                payload, http_status = dict(self._fetcher(endpoint, apn, address)), 200
            else:
                payload, http_status = self._http(endpoint, apn, address, use_address=(variant == "address"))
        except Exception:
            self._record_usage(endpoint, apn, "error", http_status)
            raise
        self._record_usage(endpoint, apn, "success", http_status)
        self._write_cache(sid, payload)
        return payload

    def _profile(self, apn: str, address: Optional[str]) -> dict[str, Any]:
        payload = self._request(PROFILE_ENDPOINT, apn, address)
        if _first(payload) is None and address:
            payload = self._request(PROFILE_ENDPOINT, apn, address, variant="address")
        return payload

    def _history(self, apn: str, address: Optional[str]) -> dict[str, Any]:
        payload = self._request(HISTORY_ENDPOINT, apn, address)
        if _first(payload) is None and address:
            payload = self._request(HISTORY_ENDPOINT, apn, address, variant="address")
        return payload

    # ---- OwnerDataProvider ---------------------------------------------------------------
    def get_owner(self, apn: str, address: Optional[str] = None) -> Optional[OwnerRecord]:
        profile = self._profile(apn, address)
        history = self._history(apn, address)
        return parse_owner(apn, profile, history, as_of=self._as_of)

    def get_sales_history(self, apn: str, address: Optional[str] = None) -> list[SaleRecord]:
        return parse_sale_records(apn, self._history(apn, address))

    def get_recorder_documents(self, apn: str, address: Optional[str] = None) -> list[RecorderDocument]:
        return parse_recorder_documents(apn, self._history(apn, address))

    def bulk_owners(self, apns: Iterable[str]) -> list[OwnerRecord]:
        out: list[OwnerRecord] = []
        for apn in apns:
            owner = self.get_owner(apn)
            if owner is not None:
                out.append(owner)
        return out
