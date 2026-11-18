"""Ownership rule: a transfer by death, trust or inheritance restarts the current owner's tenure."""
from datetime import date

import pytest

from helpers import add_territory
from test_scoring_db import AS_OF, CFG, parcel
from territory.config import load_client
from territory.owner_data.load import load_owner_layer
from territory.owner_data.sample import SampleOwnerProvider
from territory.score import run_score
from territory.scoring_engine import (
    Owner, load_transfer_types, owner_components, phrase, reason_text, resolve_tenure,
)

TYPES = CFG["transfer_types"]


def owner(last=date(1995, 3, 1)):
    return Owner(last_sale_date=last, absentee=False, is_sample=True, as_of=AS_OF)


def comps(o):
    return {c["key"]: c for c in owner_components(o, CFG, AS_OF, None)}


def test_transfer_types_config_covers_death_trust_inheritance():
    assert {v["kind"] for v in TYPES.values()} == {"death", "trust", "inheritance"}
    assert "grant deed" not in TYPES


@pytest.mark.parametrize("doc_type", sorted(load_transfer_types()))
def test_every_transfer_type_restarts_tenure(doc_type):
    o = resolve_tenure(owner(), [(date(1995, 3, 1), "grant deed"), (date(2020, 6, 1), doc_type)], TYPES)
    assert o.last_sale_date == date(2020, 6, 1) == o.transfer_date
    assert o.transfer_kind == TYPES[doc_type]["kind"]
    assert o.prior_owner_years == 25                                   # 1995-03 -> 2020-06


def test_current_tenure_starts_at_the_transfer_and_prior_tenure_is_separate():
    o = resolve_tenure(owner(), [(date(1995, 3, 1), "grant deed"), (date(2006, 11, 1), "Trust Transfer Deed")], TYPES)
    c = comps(o)
    # 20 years since the transfer (2006-11 -> 2026-11): a current-owner tenure of 20, not the 31 since 1995
    assert c["owner:years_owned"]["facts"]["years_owned"] == 20
    assert c["owner:years_owned"]["facts"]["last_sale_date"] == "2006-11-01"
    assert c["owner:years_owned"]["tenure_basis"] == "transfer"
    t = c["owner:ownership_transfer"]
    assert t["prior_owner_years"] == 11 and t["contribution"] == 0
    assert t["facts"] == {"transfer_kind": "trust", "transfer_date": "2006-11-01"}


def test_prior_owner_years_is_never_described_as_the_current_owners_tenure():
    o = resolve_tenure(owner(), [(date(1980, 1, 1), "grant deed"), (date(2004, 1, 1), "transfer on death deed")], TYPES)
    comp_list = list(comps(o).values())
    text = reason_text(comp_list, CFG)
    assert "owned 22 years" in text.lower()                            # since 2004
    assert "owned 46" not in text and "owned 24" not in text           # neither the old nor the prior tenure
    assert not any("prior" in str(c["facts"]) for c in comp_list)      # prior tenure is not a reason-text fact
    assert all(c["key"] != "owner:ownership_transfer" or phrase_free(c) for c in comp_list)


def phrase_free(c):
    return c["contribution"] == 0                                      # never printed: zero points


def test_recent_transfer_gives_no_years_owned_points_even_if_the_old_sale_was_long_ago():
    o = resolve_tenure(owner(date(1990, 1, 1)), [(date(1990, 1, 1), "grant deed"), (date(2024, 5, 1), "deed of distribution")], TYPES)
    c = comps(o)
    assert "owner:years_owned" not in c                                 # 2 years is below the 20-year tier
    assert c["owner:ownership_transfer"]["prior_owner_years"] == 34


def test_a_later_arms_length_sale_wins():
    o = owner(date(2022, 1, 1))                                         # owners row says a sale in 2022
    out = resolve_tenure(o, [(date(2010, 1, 1), "trust transfer deed"), (date(2022, 1, 1), "grant deed")], TYPES)
    assert out == o and out.transfer_date is None
    assert "owner:ownership_transfer" not in comps(out)


def test_ordinary_sales_are_unchanged_and_missing_data_is_safe():
    o = owner()
    assert resolve_tenure(o, [(date(1995, 3, 1), "grant deed")], TYPES) == o
    assert resolve_tenure(o, [], TYPES) == o
    assert resolve_tenure(None, [(date(2000, 1, 1), "trust transfer deed")], TYPES) is None
    assert resolve_tenure(o, [(None, "trust transfer deed")], TYPES) == o


def test_transfer_with_no_earlier_record_has_no_prior_tenure():
    o = resolve_tenure(owner(None), [(date(2001, 1, 1), "executor's deed")], TYPES)
    assert o.last_sale_date == date(2001, 1, 1) and o.prior_owner_years is None


def test_transfer_later_than_the_owners_row_still_applies():
    # inconsistent source data (owners.last_sale_date predates the latest sales_history transfer)
    o = resolve_tenure(owner(date(1995, 3, 1)), [(date(2015, 1, 1), "affidavit of death of joint tenant")], TYPES)
    assert o.last_sale_date == date(2015, 1, 1) and o.prior_owner_years == 19


# ---- SampleOwnerProvider is internally consistent ---------------------------------------------
def test_sample_inheritance_transfer_always_sets_last_sale_date():
    p = SampleOwnerProvider()
    transfers = 0
    for i in range(1500):
        apn = f"31000{i:05d}"
        sales = p.get_sales_history(apn)
        last = max(sales, key=lambda s: s.sale_date)
        o = p.get_owner(apn)
        assert o.last_sale_date == last.sale_date, apn
        assert o.last_sale_price == last.sale_price
        if last.doc_type != "grant deed":
            transfers += 1
            assert last.doc_type in TYPES and last.sale_price is None and last.is_sample
            assert last is max(sales, key=lambda s: s.sale_date)       # the transfer is the latest record
            assert sum(1 for s in sales if s.doc_type in TYPES) == 1
        assert all(s.is_sample and s.provider == "sample" for s in sales)
        assert o.mortgage_open in (True, False) and o.est_equity is not None
    assert 80 < transfers < 250                                          # roughly one in ten


def test_sample_provider_is_still_deterministic():
    p = SampleOwnerProvider()
    assert p.get_sales_history("3100012345") == SampleOwnerProvider().get_sales_history("3100012345")


# ---- end to end through the database ----------------------------------------------------------
def test_scoring_applies_the_rule_from_sales_history(db):
    add_territory(db)
    parcel(db, "3100000001", n=1)
    parcel(db, "3100000002", n=2)
    for apn, last in (("3100000001", date(1995, 3, 1)), ("3100000002", date(1995, 3, 1))):
        db.execute("insert into owners (apn, owner_name, mailing_address, owner_occupied, absentee, out_of_state, "
                   "last_sale_date, mortgage_open, provider, is_sample, as_of) values "
                   "(%s,'Sample Owner 0001','1 Test St',true,false,false,%s,true,'sample',true,%s)", (apn, last, AS_OF))
    db.execute("insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) values "
               "('3100000001','1995-03-01',500000,'grant deed','sample',true),"
               "('3100000001','2004-02-01',null,'trust transfer deed','sample',true),"
               "('3100000002','1995-03-01',500000,'grant deed','sample',true)")
    run_score(db, CFG, AS_OF)
    rows = {r[0]: r[1] for r in db.execute("select apn, components from scores")}
    yo = {a: next(c for c in cs if c["key"] == "owner:years_owned") for a, cs in rows.items()}
    assert yo["3100000001"]["facts"]["years_owned"] == 22 and yo["3100000001"]["tenure_basis"] == "transfer"
    assert yo["3100000002"]["facts"]["years_owned"] == 31 and yo["3100000002"]["tenure_basis"] == "sale"
    t = next(c for c in rows["3100000001"] if c["key"] == "owner:ownership_transfer")
    assert t["prior_owner_years"] == 8
    assert all(c["key"] != "owner:ownership_transfer" for c in rows["3100000002"])


def test_owner_load_appends_a_corrected_row_and_skips_identical_ones(db):
    add_territory(db)
    parcel(db, "3100000003", n=3)
    client = load_client("kaiser-team")
    first = load_owner_layer(db, client, AS_OF)
    assert first["owners_inserted"] == 1
    again = load_owner_layer(db, client, AS_OF)
    assert again["owners_inserted"] == 0 and again["sales_inserted"] == 0     # identical rows: nothing appended
    # a stale row (as if written by an older sample generator) is corrected by appending, never updating
    db.execute("truncate owners")
    db.execute("insert into owners (apn, owner_name, last_sale_date, provider, is_sample, as_of) "
               "values ('3100000003','Sample Owner 0003','1999-01-01','sample',true,%s)", (AS_OF,))
    fixed = load_owner_layer(db, client, AS_OF)
    assert fixed["owners_inserted"] == 1
    assert db.execute("select count(*) from owners").fetchone()[0] == 2
