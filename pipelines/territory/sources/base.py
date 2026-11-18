"""Source adapter interface and the shared run context."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

MatchMethod = Literal["apn", "spatial", "address", "name"]

# Confidence by match method. In-house constants: they describe how the parcel
# link was made, not how likely a seller is. Deterministic, documented here once.
CONF_APN = 0.95            # source-supplied APN found in the parcel table
CONF_SPATIAL = 0.90        # point fell inside exactly one parcel polygon
CONF_SPATIAL_AMBIGUOUS = 0.60  # point fell inside several stacked parcels
CONF_SPATIAL_FALLBACK = 0.80   # spatial match used because the APN was blank/unknown
CONF_ADDRESS = 0.70        # normalized street address matched exactly one parcel
CONF_ADDRESS_AMBIGUOUS = 0.50


class AwaitingManualDownload(Exception):
    """Raised by loaders that need a file Mike downloads by hand."""


@dataclass
class RawRecord:
    source_key: str
    source_record_id: str
    payload: dict[str, Any]
    fetched_at: Optional[datetime] = None


@dataclass
class SignalCandidate:
    """A signal before it is stored. apn is None until matching resolves a parcel."""

    signal_type: str
    signal_group: str
    source_key: str
    source_record_id: str
    confidence: float
    match_method: MatchMethod
    apn: Optional[str] = None
    signal_date: Optional[date] = None
    is_estimate: bool = False
    is_sample: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Match:
    """Result of linking one raw record to a parcel."""

    apn: Optional[str]
    method: Optional[MatchMethod] = None
    confidence: float = 0.0
    note: str = ""


NO_MATCH = Match(None)


@dataclass
class RunContext:
    """Everything an adapter needs. `local_files` lets tests (or Mike) point an
    adapter at a file instead of downloading it."""

    conn: Any                       # psycopg connection (the run's work transaction)
    run_id: str
    run_date: date
    client: Any                     # territory.config.ClientConfig
    local_files: dict[str, Path] = field(default_factory=dict)
    report_dir: Optional[Path] = None
    manual_dir: Optional[Path] = None
    _parcels: Any = None

    @property
    def parcels(self):
        from territory.parcel_index import ParcelIndex

        if self._parcels is None:
            self._parcels = ParcelIndex(self.conn)
        return self._parcels


class SourceAdapter(ABC):
    source_key: str

    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.notes: dict[str, Any] = {}   # extra lines for the match report

    def prepare(self) -> None:
        """Optional hook run before fetch (load maps, profile data, ...)."""

    @abstractmethod
    def fetch(self, run_id: str) -> Iterable[RawRecord]:
        """Fetch raw records from the source for the given source_runs id."""

    def match(self, raw: RawRecord) -> Match:
        """Link a raw record to a parcel. Must be cheap and repeatable."""
        return NO_MATCH

    @abstractmethod
    def normalize(self, raw: RawRecord) -> Iterable[SignalCandidate]:
        """Turn one raw record into zero or more signal candidates."""

    def finalize(self) -> Iterable[SignalCandidate]:
        """Signals that are not tied to one raw record (e.g. removals)."""
        return ()

    def safe_view(self, raw: RawRecord) -> dict[str, Any]:
        """Fields safe to show in a match report (no personal data)."""
        return {"source_record_id": raw.source_record_id}
