"""Source adapter interface. Concrete adapters arrive in Phase 2."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Literal, Optional

MatchMethod = Literal["apn", "spatial", "address", "name"]


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


class SourceAdapter(ABC):
    source_key: str

    @abstractmethod
    def fetch(self, run_id: str) -> Iterable[RawRecord]:
        """Fetch raw records from the source for the given source_runs id."""

    @abstractmethod
    def normalize(self, raw: RawRecord) -> Iterable[SignalCandidate]:
        """Turn one raw record into zero or more signal candidates."""
