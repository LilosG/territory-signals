"""Phase 5L: deterministic territory portfolio clustering."""
from __future__ import annotations

from datetime import date

from helpers import add_parcel, add_territory
from territory.portfolio import (
    OwnerRow, build_portfolios, entity_kind, normalize_mailing, recompute_portfolios, summarize,
)
from territory.score import run_score
from territory.scoring_engine import Owner, load_scoring_config, score_parcel

CFG = load_scoring_config()
AS_OF = date(2026, 11, 18)


def owner(apn: str, name: str | None = None, mailing: str | None = None, *, absentee=False,
          value=1_000_000.0, equity=500_000.0, sample=True) -> OwnerRow:
    return OwnerRow(apn, name, mailing, absentee, False, value, equity, sample)


# ---- normalization and entity resolution -------------------------------------------------
def test_normalization_excludes_unknown_and_numberless_addresses():
    assert normalize_mailing("9 Secret Mailing Ln, Seattle, WA 98101") == "9 secret mailing ln seattle wa 98101"
    assert normalize_mailing("  ") is None
    assert normalize_mailing("UNKNOWN") is None
    assert normalize_mailing("N/A") is None
    assert normalize_mailing("Seattle, WA") is None          # no street number


def test_entity_kind_recognizes_corporate_and_trust_names():
    assert entity_kind("PACIFIC HOLDINGS LLC") == "llc_corp"
    assert entity_kind("Smith Properties, L.P.") == "llc_corp"
    assert entity_kind("JANE DOE TRUST") == "trust"
    assert entity_kind("ESTATE OF JANE DOE") == "trust"
    assert entity_kind("Sample Owner 1234") is None


def test_build_portfolios_groups_by_llc_name_and_mailing_address():
    rows = build_portfolios([
        owner("A", "PACIFIC HOLDINGS LLC", "1 Corp Way"),
        owner("B", "PACIFIC HOLDINGS LLC", "2 Other Way"),
        owner("C", None, "9 Shared Mail Ln"),
        owner("D", None, "9 Shared Mail Ln"),
        owner("E", "Sample Owner 0005", "5 Unique Ln"),
    ])
    by_apn = {r.apn: r for r in rows}
    assert by_apn["A"].portfolio_key == by_apn["B"].portfolio_key
    assert by_apn["A"].entity_type == "llc_corp" and by_apn["A"].territory_parcel_count == 2
    assert by_apn["A"].total_est_value == 2_000_000.0 and by_apn["A"].total_est_equity == 1_000_000.0
    assert by_apn["C"].portfolio_key == by_apn["D"].portfolio_key
    assert by_apn["C"].entity_type == "individual_multi" and by_apn["C"].territory_parcel_count == 2
    assert by_apn["E"].entity_type == "single" and by_apn["E"].territory_parcel_count == 1
    assert by_apn["E"].portfolio_key == "apn:E"


def test_build_portfolios_ignores_blank_addresses_and_keeps_sample_flag():
    rows = build_portfolios([
        owner("A", None, ""), owner("B", None, "unknown"), owner("C", None, None),
        owner("D", "Smith Family Trust", "4 Ln", sample=False),
        owner("E", "Smith Family Trust", "5 Ln", sample=False),
    ])
    by_apn = {r.apn: r for r in rows}
    assert by_apn["A"].entity_type == by_apn["B"].entity_type == by_apn["C"].entity_type == "single"
    assert by_apn["D"].entity_type == "trust" and by_apn["D"].territory_parcel_count == 2
    assert by_apn["D"].is_sample is False


def test_summary_counts_portfolios_and_parcels():
    rows = build_portfolios([
        owner("A", "PACIFIC HOLDINGS LLC", "1 Corp Way"),
        owner("B", "PACIFIC HOLDINGS LLC", "2 Other Way"),
        owner("C", None, "9 Shared Mail Ln"),
        owner("D", None, "9 Shared Mail Ln"),
        owner("E", "Sample Owner 0005", "5 Unique Ln"),
    ])
    s = summarize(rows)
    assert s["parcels"] == 5 and s["portfolios"] == 2 and s["multi_parcel_parcels"] == 4
    assert s["portfolios_by_entity"] == {"llc_corp": 1, "individual_multi": 1}


# ---- database recompute -------------------------------------------------------------------
def _seed_owners(db):
    add_territory(db)
    add_parcel(db, "6100000001", -117.20, 32.80)
    add_parcel(db, "6100000002", -117.21, 32.81)
    add_parcel(db, "6100000003", -117.22, 32.82)
    db.execute(
        "insert into owners (apn, owner_name, mailing_address, owner_occupied, absentee, out_of_state, "
        "last_sale_date, mortgage_open, est_value, est_equity, provider, is_sample, as_of) values "
        "('6100000001','PACIFIC HOLDINGS LLC','1 Corp Way',false,true,false,'2001-01-01',false,2000000,900000,'sample',true,%s),"
        "('6100000002','PACIFIC HOLDINGS LLC','2 Other Way',false,true,false,'2001-01-01',false,3000000,1500000,'sample',true,%s),"
        "('6100000003','Sample Owner 0003','9 Shared Mail Ln',false,false,false,'2001-01-01',false,1000000,400000,'sample',true,%s)",
        (AS_OF, AS_OF, AS_OF))


def test_recompute_portfolios_writes_latest_rows_and_is_idempotent(db):
    _seed_owners(db)
    first = recompute_portfolios(db, computed_at=__import__("datetime").datetime(2026, 11, 18, 1))
    assert first["parcels"] == 3 and first["portfolios"] == 1 and first["multi_parcel_parcels"] == 2
    rows = db.execute(
        "select apn, portfolio_key, entity_type, territory_parcel_count, total_est_value, total_est_equity, is_sample "
        "from parcel_portfolios order by apn").fetchall()
    assert rows[0][0:4] == ("6100000001", "name:pacific holdings llc", "llc_corp", 2)
    assert rows[1][0:4] == ("6100000002", "name:pacific holdings llc", "llc_corp", 2)
    assert rows[2][0:4] == ("6100000003", "apn:6100000003", "single", 1)
    assert float(rows[0][4]) == 5_000_000.0 and float(rows[0][5]) == 2_400_000.0
    assert all(r[6] is True for r in rows)
    latest = db.execute("select count(*) from latest_parcel_portfolios").fetchone()[0]
    assert latest == 3

    second = recompute_portfolios(db, computed_at=__import__("datetime").datetime(2026, 11, 19, 1))
    assert second["portfolios"] == 1
    assert db.execute("select count(*) from parcel_portfolios").fetchone()[0] == 3     # refreshed, not appended
    assert db.execute("select count(*) from latest_parcel_portfolios").fetchone()[0] == 3


# ---- scoring integration ------------------------------------------------------------------
def test_score_parcel_adds_the_portfolio_modifier_for_multi_parcel_investors():
    o = Owner(last_sale_date=date(2001, 1, 1), absentee=True, out_of_state=False, mortgage_open=True,
              portfolio_parcel_count=3, portfolio_entity_type="llc_corp",
              portfolio_key="name:pacific holdings llc", portfolio_is_sample=True)
    r = score_parcel([], o, CFG, AS_OF, {}, None)
    comp = next(c for c in r["components"] if c["key"] == "owner:portfolio_owner_multi")
    assert comp["raw_weight"] == 6 and comp["contribution"] == 6
    assert comp["facts"]["territory_parcel_count"] == 3 and comp["facts"]["entity_type"] == "llc_corp"
    assert comp["is_sample"] is True
    assert "holds 3 parcels in the territory" in r["reason_text"]


def test_score_parcel_skips_the_portfolio_modifier_for_a_single_owner_occupied_parcel():
    for count, entity_type, absentee in ((1, "single", False), (2, "single", False)):
        o = Owner(last_sale_date=date(2001, 1, 1), absentee=absentee, out_of_state=False, mortgage_open=True,
                  portfolio_parcel_count=count, portfolio_entity_type=entity_type)
        r = score_parcel([], o, CFG, AS_OF, {}, None)
        assert not any(c["key"] == "owner:portfolio_owner_multi" for c in r["components"])


def test_run_score_reads_the_portfolio_table(db):
    _seed_owners(db)
    db.execute("update parcels set land_use='11' where apn like '610000000%'")
    db.execute(
        "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
        "confidence, match_method, details) values "
        "('6100000001','permit_approved','pre_sale_prep',%s,'dev_permits','P1',0.95,'apn',%s),"
        "('6100000002','permit_approved','pre_sale_prep',%s,'dev_permits','P2',0.95,'apn',%s)",
        (AS_OF, '{"approval_type":"Electrical Permit"}', AS_OF, '{"approval_type":"Electrical Permit"}'))
    recompute_portfolios(db)
    run_score(db, CFG, AS_OF)
    rows = db.execute(
        "select apn, components from latest_scores where apn in ('6100000001','6100000002') order by apn").fetchall()
    assert len(rows) == 2
    for apn, components in rows:
        comp = next(c for c in components if c["key"] == "owner:portfolio_owner_multi")
        assert comp["facts"]["territory_parcel_count"] == 2
        assert comp["raw_weight"] == 6
