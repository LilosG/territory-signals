"""Deterministic, clearly fake owner data used until ATTOM is configured."""
from __future__ import annotations

import hashlib
import random
import re
from datetime import date, timedelta
from typing import Iterable

from .base import OwnerDataProvider, OwnerRecord, SaleRecord

SAMPLE_AS_OF = date(2026, 1, 1)
_OUT_OF_STATE = ["Austin, TX 78701", "Phoenix, AZ 85004", "Seattle, WA 98101", "Denver, CO 80202"]
_IN_STATE = ["Los Angeles, CA 90012", "San Francisco, CA 94103", "Irvine, CA 92618"]
_STREETS = ["Prospect St", "Garnet Ave", "Mission Blvd", "Girard Ave", "Ocean Front Walk", "Turquoise St"]


def _rng(apn: str) -> random.Random:
    digest = hashlib.sha256(f"territory-sample:{apn}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _last4(apn: str) -> str:
    digits = re.sub(r"\D", "", apn)
    return digits[-4:].rjust(4, "0")


class SampleOwnerProvider(OwnerDataProvider):
    provider = "sample"

    def _sales(self, apn: str) -> list[SaleRecord]:
        r = _rng(apn)
        count = r.randint(1, 3)
        sales: list[SaleRecord] = []
        price = r.randrange(350_000, 900_000, 5_000)
        sale_date = SAMPLE_AS_OF - timedelta(days=r.randint(365 * 12, 365 * 30))
        for _ in range(count):
            sales.append(SaleRecord(apn, sale_date, float(price), "grant deed", "sample", True))
            sale_date += timedelta(days=r.randint(365 * 3, 365 * 9))
            price = int(price * r.uniform(1.4, 2.2) // 5_000 * 5_000)
            if sale_date >= SAMPLE_AS_OF:
                break
        return sales

    def get_owner(self, apn: str) -> OwnerRecord:
        r = _rng(apn)
        sales = self._sales(apn)
        last = sales[-1]
        est_value = float(r.randrange(1_100_000, 4_200_000, 10_000))
        mortgage_open = r.random() < 0.55
        balance = last.sale_price * r.uniform(0.3, 0.7) if mortgage_open else 0.0
        absentee = r.random() < 0.3
        out_of_state = absentee and r.random() < 0.5
        if absentee:
            mailing = f"{r.randint(100, 9999)} {r.choice(_STREETS)}, " + r.choice(
                _OUT_OF_STATE if out_of_state else _IN_STATE
            )
        else:
            mailing = f"{r.randint(100, 9999)} {r.choice(_STREETS)}, San Diego, CA 92109"
        return OwnerRecord(
            apn=apn,
            owner_name=f"Sample Owner {_last4(apn)}",
            mailing_address=mailing,
            owner_occupied=not absentee,
            absentee=absentee,
            out_of_state=out_of_state,
            last_sale_date=last.sale_date,
            last_sale_price=last.sale_price,
            mortgage_open=mortgage_open,
            est_value=est_value,
            est_equity=round(est_value - balance, 2),
            provider="sample",
            is_sample=True,
            as_of=SAMPLE_AS_OF,
        )

    def get_sales_history(self, apn: str) -> list[SaleRecord]:
        return self._sales(apn)

    def bulk_owners(self, apns: Iterable[str]) -> list[OwnerRecord]:
        return [self.get_owner(a) for a in apns]
