"""Owner data provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


class NotConfiguredError(RuntimeError):
    """Raised when a provider is used without its required configuration."""


@dataclass(frozen=True)
class OwnerRecord:
    apn: str
    owner_name: str
    mailing_address: str
    owner_occupied: bool
    absentee: bool
    out_of_state: bool
    last_sale_date: Optional[date]
    last_sale_price: Optional[float]
    mortgage_open: bool
    est_value: float
    est_equity: float
    provider: str
    is_sample: bool
    as_of: date


@dataclass(frozen=True)
class SaleRecord:
    apn: str
    sale_date: date
    sale_price: Optional[float]      # None for a transfer with no price (death, trust, inheritance)
    doc_type: str
    provider: str
    is_sample: bool


class OwnerDataProvider(ABC):
    @abstractmethod
    def get_owner(self, apn: str) -> Optional[OwnerRecord]: ...

    @abstractmethod
    def get_sales_history(self, apn: str) -> list[SaleRecord]: ...

    @abstractmethod
    def bulk_owners(self, apns: Iterable[str]) -> list[OwnerRecord]: ...
