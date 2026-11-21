"""Phase 5L: City of San Diego code enforcement adapter."""
from __future__ import annotations

import json
from datetime import date

from helpers import FIXTURES, RUN_DATE, add_parcel, add_territory, run
from territory.sources.code_enforcement import clean_apn, clean_description, parse_date

FIXTURE = FIXTURES / "code_enforcement_fixture.csv"


def _setup(db):
    add_territory(db)
    add_parcel(db, "6000000001", -117.20, 32.80, zoning="RS-1-7", lot=6000)
    add_parcel(db, "6000000002", -117.21, 32.81, zoning="RS-1-7", lot=6000)
    add_parcel(db, "6000000003", -117.22, 32.82, zoning="RS-1-7", lot=6000)


# ---- parsing helpers ---------------------------------------------------------------------
def test_clean_apn_accepts_only_ten_digits():
    assert clean_apn("600-000-0001") == "6000000001"
    assert clean_apn("6000000001") == "6000000001"
    assert clean_apn("") is None and clean_apn(None) is None and clean_apn("123") is None


def test_clean_description_drops_owner_brackets_and_reassignment_notes():
    assert clean_description("GARAGE CONVERSN -   [Addr:  100 TEST WAY   Owner: JANE DOE ]") == "GARAGE CONVERSN"
    assert clean_description("STRUC HAZARD - REASSIGNED TO KAREN M.") == "STRUC HAZARD"
    assert clean_description("FENCE/DISREPAIR - [Addr: 400 TEST WAY Owner: PAT DOE]") == "FENCE/DISREPAIR"


def test_parse_date_accepts_source_dates_and_blanks():
    assert parse_date("2026-06-01") == date(2026, 6, 1)
    assert parse_date("") is None and parse_date(None) is None and parse_date("not a date") is None


# ---- adapter run -------------------------------------------------------------------------
def test_code_enforcement_emits_open_closed_and_spatial_signals(db, tmp_path):
    _setup(db)
    o = run("code_enforcement", local_files={"code_enforcement": FIXTURE}, report_dir=tmp_path)
    assert o.status == "success", o.error
    assert (o.rows_fetched, o.rows_matched, o.signals_written) == (4, 4, 3)

    rows = db.execute(
        "select apn, signal_type, signal_group, signal_date, source_record_id, match_method, confidence, "
        "is_sample, is_estimate, details from signals order by source_record_id, signal_type").fetchall()
    got = {(r[0], r[1], r[2], str(r[3]), r[4], r[5]) for r in rows}
    assert got == {
        ("6000000001", "code_violation_open", "distress", "2026-06-01", "CE-OPEN-1", "apn"),
        ("6000000002", "code_violation_closed", "pre_sale_prep", "2026-10-01", "CE-CLOSED-RECENT", "apn"),
        ("6000000001", "code_violation_open", "distress", "2026-05-01", "CE-SPATIAL", "spatial"),
    }
    assert all(r[7] is False and r[8] is False for r in rows)          # public records, not sample or estimates
    assert all(0.8 <= float(r[6]) <= 0.95 for r in rows)

    by_id = {r[4]: r[9] for r in rows}
    open_case = by_id["CE-OPEN-1"]
    assert open_case["status"] == "open" and open_case["close_date"] is None
    assert open_case["violation_category"] == "GARAGE CONVERSN"
    assert open_case["case_source"] == "Citizen Complaint" and open_case["workgroup"] == "Zoning"
    closed = by_id["CE-CLOSED-RECENT"]
    assert closed["status"] == "closed" and closed["close_date"] == "2026-10-01"

    # A closed case older than 180 days is stored as a raw record but never scores.
    assert db.execute("select count(*) from signals where source_record_id='CE-CLOSED-OLD'").fetchone()[0] == 0
    assert db.execute("select count(*) from raw_records where source_record_id='CE-CLOSED-OLD'").fetchone()[0] == 1


def test_code_enforcement_never_stores_personal_contact_fields(db, tmp_path):
    _setup(db)
    assert run("code_enforcement", local_files={"code_enforcement": FIXTURE}, report_dir=tmp_path).status == "success"
    payloads = json.dumps([r[0] for r in db.execute("select payload from raw_records")])
    details = json.dumps([r[0] for r in db.execute("select details from signals")])
    for forbidden in ("Jane Investigator", "Bob Inspector", "619-555-0100", "jane@example.com",
                      "investigator_phone_number", "investigator_email_address", "JANE DOE", "Owner:"):
        assert forbidden not in payloads, forbidden
        assert forbidden not in details, forbidden


def test_code_enforcement_skips_records_outside_the_territory(db, tmp_path):
    _setup(db)
    run("code_enforcement", local_files={"code_enforcement": FIXTURE}, report_dir=tmp_path)
    assert db.execute("select count(*) from raw_records where source_record_id in "
                      "('CE-OUTSIDE-APN','CE-UNPLACEABLE')").fetchone()[0] == 0
    assert RUN_DATE > date(2026, 10, 1)          # the recent closed case is inside the 180-day window


def test_packaged_fallback_file_is_used_when_no_download_cache_exists(monkeypatch, tmp_path):
    import territory.sources.code_enforcement as ce
    monkeypatch.setattr(ce, "DATA_DIR", tmp_path)
    p = ce.newest_cached_file()
    assert p is not None and p.name == "code_enforcement_fallback.csv" and p.exists()
