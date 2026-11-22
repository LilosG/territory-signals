"""Phase 6: ATTOM live provider, permanent cache, quota governor and recorder signals.

All HTTP is replaced by recorded JSON fixtures in tests/fixtures/attom/; the suite makes no live ATTOM
call and spends $0.00.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from helpers import add_parcel, add_territory
from territory.config import load_client
from territory.owner_data.attom import (
    AttomOwnerProvider, QuotaExceededError, parse_owner, parse_recorder_documents, parse_sale_records,
    recorder_signal_candidates,
)
from territory.owner_data.sample import SampleOwnerProvider
from territory.enrich_attom import enrich_owners, ranked_apns
from territory.portfolio import recompute_portfolios
from territory.score import run_score
from territory.scoring_engine import load_scoring_config

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "attom"
AS_OF = date(2026, 11, 18)
OUT_OF_STATE = "3461201100"
INHERITANCE = "3500701802"
NOTICE = "3504004715"
LLC_A, LLC_B = "3505101234", "3505101235"
NO_DATA = "3506000000"


def fixture_fetcher(calls: list | None = None):
    def fetch(endpoint: str, apn: str, address: str | None = None):
        if calls is not None:
            calls.append((endpoint, apn, address))
        path = FIXTURES / f"{apn}_{endpoint}.json"
        return json.loads(path.read_text()) if path.exists() else {"property": []}
    return fetch


def payload(apn: str, endpoint: str) -> dict:
    return json.loads((FIXTURES / f"{apn}_{endpoint}.json").read_text())


# ---- pure parsing -------------------------------------------------------------------------
def test_out_of_state_free_and_clear_owner():
    owner = parse_owner(OUT_OF_STATE, payload(OUT_OF_STATE, "expandedprofile"),
                        payload(OUT_OF_STATE, "expandedhistory"), as_of=AS_OF)
    assert owner is not None
    assert owner.owner_name == "JOHN A DOE"
    assert owner.out_of_state is True and owner.absentee is True and owner.owner_occupied is False
    assert "Seattle" in owner.mailing_address and owner.mortgage_open is False
    assert owner.est_value == 3_100_000 and owner.est_equity == 3_100_000
    assert owner.last_sale_date == date(2012, 5, 1) and owner.last_sale_price == 777_777
    assert owner.provider == "attom" and owner.is_sample is False


def test_inheritance_transfer_and_notice_of_default_are_classified():
    inheritance = parse_recorder_documents(INHERITANCE, payload(INHERITANCE, "expandedhistory"))
    assert [(d.doc_type, d.is_transfer, d.is_distress) for d in inheritance] == [
        ("Affidavit of Death", True, False), ("Grant Deed", False, False), ("Grant Deed", False, False)]
    assert inheritance[0].kind == "death"
    signals = recorder_signal_candidates(INHERITANCE, inheritance)
    assert signals == [{"signal_type": "ownership_transfer_inheritance", "signal_group": "life_event",
                        "signal_date": date(2025, 10, 1), "doc_type": "Affidavit of Death",
                        "transfer_kind": "death", "label": "Affidavit of death"}]

    notice_docs = parse_recorder_documents(NOTICE, payload(NOTICE, "expandedhistory"))
    notice_signals = recorder_signal_candidates(NOTICE, notice_docs)
    assert notice_signals == [{"signal_type": "notice_of_default", "signal_group": "distress",
                               "signal_date": date(2026, 9, 20), "doc_type": "Notice of Default",
                               "notice_kind": "preforeclosure", "label": "Notice of default"}]
    # A distress filing is not a sale and must not enter sales_history (it would otherwise suppress scoring).
    assert [s.doc_type for s in parse_sale_records(NOTICE, payload(NOTICE, "expandedhistory"))] == ["Grant Deed"]


def test_llc_owner_payload_parses_as_an_entity():
    owner = parse_owner(LLC_A, payload(LLC_A, "expandedprofile"), payload(LLC_A, "expandedhistory"), as_of=AS_OF)
    assert owner is not None and owner.owner_name == "PACIFIC HOLDINGS LLC"
    assert owner.absentee is True and owner.out_of_state is False


def test_no_property_payload_is_not_an_owner_row():
    assert parse_owner(NO_DATA, payload(NO_DATA, "expandedprofile"),
                       payload(NO_DATA, "expandedhistory"), as_of=AS_OF) is None


# ---- cache and quota ----------------------------------------------------------------------
def test_permanent_cache_makes_zero_duplicate_calls(db):
    calls: list = []
    p = AttomOwnerProvider(conn=db, fetcher=fixture_fetcher(calls), max_calls=10, as_of=AS_OF)
    assert p.get_owner(OUT_OF_STATE) is not None
    assert len(calls) == 2                                   # profile + history, once
    first_owner = p.get_owner(OUT_OF_STATE)
    p.get_sales_history(OUT_OF_STATE)
    p.get_recorder_documents(OUT_OF_STATE)
    assert len(calls) == 2                                   # cache: no calls at all
    assert first_owner.provider == "attom"
    assert db.execute("select count(*) from raw_records where source_key='attom'").fetchone()[0] == 2
    assert db.execute("select count(*) from api_usage_log where source_key='attom'").fetchone()[0] == 2
    cached = db.execute("select payload::text from raw_records where source_key='attom'").fetchall()
    blob = " ".join(r[0] for r in cached)
    assert "619-555-9999" not in blob and "123-45-6789" not in blob and "jdoe@example.test" not in blob
    assert "[redacted]" in blob                              # privacy fields are blanked before caching


def test_refresh_days_expires_the_cache(db):
    calls: list = []
    p = AttomOwnerProvider(conn=db, fetcher=fixture_fetcher(calls), max_calls=10, refresh_days=0, as_of=AS_OF)
    p.get_owner(OUT_OF_STATE)
    assert len(calls) == 2
    p.get_owner(OUT_OF_STATE)
    assert len(calls) == 4                                   # zero-day refresh always refetches
    assert db.execute("select count(*) from raw_records where source_key='attom'").fetchone()[0] == 4


def test_max_calls_is_a_strict_daily_budget(db):
    calls: list = []
    p = AttomOwnerProvider(conn=db, fetcher=fixture_fetcher(calls), max_calls=2, as_of=AS_OF)
    p.get_owner(OUT_OF_STATE)                                # exactly 2 calls
    assert p.daily_calls() == 2
    with pytest.raises(QuotaExceededError, match="daily call budget"):
        p.get_owner(LLC_A)
    assert p.daily_calls() == 2 and len(calls) == 2
    assert db.execute("select count(*) from api_usage_log").fetchone()[0] == 2


def test_provider_still_requires_a_key_without_a_fetcher(monkeypatch):
    monkeypatch.delenv("ATTOM_API_KEY", raising=False)
    with pytest.raises(Exception, match="ATTOM_API_KEY"):
        AttomOwnerProvider()


# ---- hybrid enrichment and scoring --------------------------------------------------------
def _seed_parcels(db, apns):
    add_territory(db)
    for i, apn in enumerate(apns):
        add_parcel(db, apn, -117.30 + i * 0.001, 32.85, lot=6000)
    db.execute("update parcels set land_use='11' where apn = any(%s)", (list(apns),))


def test_hybrid_enrichment_writes_real_rows_and_keeps_labeled_sample_fallback(db):
    all_apns = [OUT_OF_STATE, INHERITANCE, NOTICE, LLC_A, LLC_B, NO_DATA, "9999999999"]
    _seed_parcels(db, all_apns)
    db.execute(
        "insert into owners (apn, owner_name, mailing_address, owner_occupied, absentee, out_of_state, "
        "last_sale_date, mortgage_open, est_value, est_equity, provider, is_sample, as_of) "
        "values ('9999999999','Sample Owner 9999','1 Sample Ln',true,false,false,'2001-01-01',false,"
        "1000000,500000,'sample',true,%s)", (AS_OF,))

    client = load_client("kaiser-team")
    assert client.owner_data_provider == "hybrid"
    result = enrich_owners(db, client, limit=6, max_calls=50, as_of=AS_OF, fetcher=fixture_fetcher())

    assert result.selected == 6                              # deterministic APN order, 9999999999 left out
    assert result.attom_owners == 5 and result.sample_fallback_owners == 1
    assert result.inheritance_signals == 1 and result.notice_signals == 1
    rows = {(r[0], r[1], bool(r[2])) for r in db.execute("select apn, provider, is_sample from owners")}
    for apn in (OUT_OF_STATE, INHERITANCE, NOTICE, LLC_A, LLC_B):
        assert (apn, "attom", False) in rows
    assert (NO_DATA, "sample", True) in rows                 # no property: labeled sample fallback
    assert ("9999999999", "sample", True) in rows            # unselected parcel keeps its sample row

    # Recorder signals are real, labeled, and the distress filing did not become a sale.
    sig = {(r[0], r[1], bool(r[2])) for r in db.execute(
        "select apn, signal_type, is_sample from signals where source_key='attom'")}
    assert sig == {(INHERITANCE, "ownership_transfer_inheritance", False), (NOTICE, "notice_of_default", False)}
    assert db.execute("select count(*) from sales_history where apn=%s", (NOTICE,)).fetchone()[0] == 1


def test_enriched_inheritance_enables_quiet_inheritance_recipe(db):
    _seed_parcels(db, [INHERITANCE])
    enrich_owners(db, load_client("kaiser-team"), limit=1, max_calls=10, as_of=AS_OF, fetcher=fixture_fetcher())
    recompute_portfolios(db, AS_OF)
    run_score(db, load_scoring_config(), AS_OF)
    row = db.execute("select recipe_matches, uses_sample_data, components from scores where apn=%s",
                     (INHERITANCE,)).fetchone()
    assert row is not None
    assert "quiet_inheritance" in row[0]
    assert row[1] is False
    assert not any(c["key"] == "ownership_transfer_inheritance" for c in row[2])   # context only: never scores


def test_notice_of_default_scores_at_weight_35_and_opens_financial_pressure(db):
    _seed_parcels(db, [NOTICE])
    enrich_owners(db, load_client("kaiser-team"), limit=1, max_calls=10, as_of=AS_OF, fetcher=fixture_fetcher())
    run_score(db, load_scoring_config(), AS_OF)
    components, recipes = db.execute("select components, recipe_matches from scores where apn=%s",
                                     (NOTICE,)).fetchone()
    comp = next(c for c in components if c["key"] == "notice_of_default")
    assert comp["raw_weight"] == 35 and comp["half_life_days"] == 180 and comp["family"] == "financial"
    assert comp["is_sample"] is False
    assert "financial_pressure" in recipes


def test_priority_ranking_puts_candidates_before_higher_sample_scores(db):
    _seed_parcels(db, [OUT_OF_STATE, LLC_A])
    db.execute(
        "insert into scores (apn, score, components, model_version) values "
        "(%s, 70, %s, 'test'), (%s, 40, %s, 'test')",
        (OUT_OF_STATE, json.dumps([{"kind": "owner", "key": "owner:years_owned", "contribution": 20, "is_sample": True}]),
         LLC_A, json.dumps([{"kind": "signal", "key": "tax_default", "contribution": 35, "is_sample": False}])))
    ranked = ranked_apns(db, load_scoring_config(), 2)
    assert [r["apn"] for r in ranked] == [LLC_A, OUT_OF_STATE]     # candidate first, then non-sample points
    assert ranked[0]["candidate"] is True
