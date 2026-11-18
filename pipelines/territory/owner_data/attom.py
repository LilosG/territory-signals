"""ATTOM owner data provider skeleton. No API calls until Phase 6."""
from __future__ import annotations

import os
from typing import Iterable, Optional

from .base import NotConfiguredError, OwnerDataProvider, OwnerRecord, SaleRecord


class AttomOwnerProvider(OwnerDataProvider):
    provider = "attom"

    def __init__(self) -> None:
        key = os.environ.get("ATTOM_API_KEY")
        if not key:
            raise NotConfiguredError(
                "ATTOM_API_KEY is not set. Add it to the environment to use the ATTOM provider; "
                "until then use SampleOwnerProvider (owner_data_provider: sample)."
            )
        self._api_key = key

    def get_owner(self, apn: str) -> Optional[OwnerRecord]:
        raise NotImplementedError("ATTOM calls are implemented in Phase 6")

    def get_sales_history(self, apn: str) -> list[SaleRecord]:
        raise NotImplementedError("ATTOM calls are implemented in Phase 6")

    def bulk_owners(self, apns: Iterable[str]) -> list[OwnerRecord]:
        raise NotImplementedError("ATTOM calls are implemented in Phase 6")
