"""Database-backed Phase 3 tests: residential filter, suppression, score history, owner layer,
permit re-derivation, superseded_by. Everything runs on the territory_test database."""
import json
from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest
import yaml
from psycopg.types.json import Jsonb

from helpers import add_parcel, add_territory
from territory import permit_rules
from territory.config import load_client
from territory.owner_data.load import load_owner_layer
from territory.permit_rederive import rederive
from territory.score import load_residential, run_score, write_land_use_profile
from territory.scoring_engine import load_scoring_config

CFG = load_scoring_config()
AS_OF = date(2026, 11, 18)


def parcel(db, apn, land_use="11", area="La Jolla", n=0):
    add_parcel(db, apn, -117.25 + n * 0.001, 32.85, planning_area=area)
    db.execute("update parcels set land_use=%s where apn=%s", (land_use, apn))


def run_id(db, key="test"):
    return db.execute("insert into source_runs (source_key, status) values (%s, 'success') returning id",
                      (key,)).fetchone()[0]


def add_signal(db, apn, type_, group="other", on=AS_OF, details=None, rid=None, key=None):
    rid = rid or run_id(db)
    return db.execute(
        "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
        "run_id, confidence, match_method, details) values (%s,%s,%s,%s,'test',%s,%s,0.9,'apn',%s) returning id",
        (apn, type_, group, on, key or f"{apn}-{type_}-{group}-{on}", rid, Jsonb(details or {}))).fetchone()[0]


def scores(db):
    return {r[0]: r for r in db.execute(
        "select apn, score, recipe_matches, reason_text, uses_sample_data, components from scores")}


# ---- residential filter ---------------------------------------------------------------------
def test_only_residential_land_uses_are_scored(db):
    add_territory(db)
    codes = CFG["residential_codes"]
    assert set(codes) == {"11", "17", "12", "13", "14"}
    for i, code in enumerate(codes + ["15", "7", "21", "10", None]):
        parcel(db, f"300000000{i}", code, n=i)
        add_signal(db, f"300000000{i}", "tax_default", on=AS_OF)           # signal on every parcel
    s = run_score(db, CFG, AS_OF)
    got = scores(db)
    assert set(got) == {f"300000000{i}" for i in range(len(codes))}          # non-residential: no score
    assert s["scored"] == len(codes) and s["residential_parcels"] == len(codes)
    assert s["non_residential_parcels"] == 5
    assert [r[0] for r in load_residential(db, CFG)] == sorted(got)


def test_land_use_profile_lists_every_distinct_code(db, tmp_path):
    add_territory(db)
    for i, code in enumerate(["11", "11", "15", "7", None]):
        parcel(db, f"300000010{i}", code, n=i)
    path = write_land_use_profile(db, CFG, tmp_path, parcels_csv=tmp_path / "none.csv")
    rows = [l.split(",") for l in path.read_text().splitlines()]
    header, body = rows[0], rows[1:]
    codes = {r[0]: r for r in body}
    assert set(codes) == {"11", "15", "7", "(blank)"}
    assert codes["11"][1] == "2" and codes["11"][header.index("scored_as_residential")] == "yes"
    assert codes["15"][header.index("scored_as_residential")] == "no"


# ---- suppression ------------------------------------------------------------------------------
def test_recent_sale_and_active_suppression_remove_the_score(db):
    add_territory(db)
    for i in range(6):
        parcel(db, f"300000020{i}", n=i)
    sale = lambda apn, d: db.execute(
        "insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) "
        "values (%s,%s,1,'grant deed','sample',true)", (apn, d))
    sale("3000000200", AS_OF - timedelta(days=200))              # recent: suppressed
    sale("3000000201", date(2024, 11, 19))                       # 23 months 29 days ago: suppressed
    sale("3000000202", date(2024, 11, 18))                       # exactly 24 months: suppressed
    sale("3000000203", date(2024, 11, 17))                       # just over 24 months: scored
    db.execute("insert into suppressions (apn, reason, until_date) values ('3000000204','do not contact',null)")
    db.execute("insert into suppressions (apn, reason, until_date) values ('3000000205','expired',%s)",
               (AS_OF - timedelta(days=1),))
    s = run_score(db, CFG, AS_OF)
    assert set(scores(db)) == {"3000000203", "3000000205"}
    assert s["suppressed"]["sale within 24 months"] == 3 and s["suppressed"]["suppression"] == 1


def test_active_suppression_with_future_until_date(db):
    add_territory(db)
    parcel(db, "3000000300")
    db.execute("insert into suppressions (apn, reason, until_date) values ('3000000300','hold',%s)",
               (AS_OF + timedelta(days=30),))
    run_score(db, CFG, AS_OF)
    assert scores(db) == {}


# ---- the scoring step ---------------------------------------------------------------------------
def test_scores_are_append_only_history_with_required_columns(db):
    add_territory(db)
    parcel(db, "3000000400")
    add_signal(db, "3000000400", "tax_default", on=AS_OF - timedelta(days=10),
               details={"tax_defaulted_on": "2025-06-30"})
    run_score(db, CFG, AS_OF, datetime(2026, 11, 18, 1, tzinfo=timezone.utc))
    run_score(db, CFG, AS_OF, datetime(2026, 11, 18, 2, tzinfo=timezone.utc))
    rows = db.execute("select score, model_version, uses_sample_data, recipe_matches, components, "
                      "reason_text from scores where apn='3000000400' order by scored_at").fetchall()
    assert len(rows) == 2 and rows[0][:4] == rows[1][:4]
    assert rows[0][1] == "v0.2-handset" and rows[0][2] is False
    assert rows[0][4][0]["signal_id"] and rows[0][5].startswith("Tax-defaulted")
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update scores set score = 1")
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("delete from scores")


def test_scoring_is_deterministic_on_the_database(db):
    add_territory(db)
    load_client("kaiser-team")
    for i in range(5):
        parcel(db, f"300000050{i}", n=i)
        add_signal(db, f"300000050{i}", "permit_approved", "pre_sale_prep", on=AS_OF - timedelta(days=i * 20),
                   details={"approval_type": "Electrical Permit"})
    run_score(db, CFG, AS_OF, datetime(2026, 11, 18, 1, tzinfo=timezone.utc))
    run_score(db, CFG, AS_OF, datetime(2026, 11, 18, 2, tzinfo=timezone.utc))
    a = db.execute("select apn, score, components::text, reason_text, recipe_matches from scores "
                   "where scored_at=%s order by apn", (datetime(2026, 11, 18, 1, tzinfo=timezone.utc),)).fetchall()
    b = db.execute("select apn, score, components::text, reason_text, recipe_matches from scores "
                   "where scored_at=%s order by apn", (datetime(2026, 11, 18, 2, tzinfo=timezone.utc),)).fetchall()
    assert a == b and len(a) == 5


def test_superseded_signals_are_ignored_by_scoring(db):
    add_territory(db)
    parcel(db, "3000000600")
    sid = add_signal(db, "3000000600", "tax_default", on=AS_OF)
    rid = run_id(db, "permit_rederive")
    db.execute("update signals set superseded_by=%s where id=%s", (rid, sid))
    run_score(db, CFG, AS_OF)
    assert scores(db)["3000000600"][1] == 0


def test_stro_snapshot_rule_in_the_database(db):
    add_territory(db)
    for i in range(3):
        parcel(db, f"300000070{i}", n=i)
    for d in (date(2026, 11, 1), date(2026, 11, 8), date(2026, 11, 15)):
        add_signal(db, "3000000700", "stro_license_active", "stro", on=d, key=f"L1-{d}")   # repeated daily rows
    add_signal(db, "3000000701", "stro_license_active", "stro", on=date(2026, 11, 1), key="L2")  # only an old row
    add_signal(db, "3000000702", "stro_license_active", "stro", on=date(2026, 11, 15), key="L3")
    run_score(db, CFG, AS_OF)
    got = scores(db)
    assert got["3000000700"][1] == 5 and got["3000000702"][1] == 5 and got["3000000701"][1] == 0


def test_fire_recipe_only_when_fire_zones_are_loaded(db):
    add_territory(db)
    parcel(db, "3000000800")
    run_score(db, CFG, AS_OF)
    assert "insurance_squeeze" not in (scores(db)["3000000800"][2] or [])
    add_signal(db, "3000000800", "fire_hazard_zone", "risk", on=AS_OF, details={"hazard_class": "Very High"})
    run_score(db, CFG, AS_OF, datetime(2026, 12, 1, tzinfo=timezone.utc))
    row = db.execute("select score, recipe_matches from scores order by scored_at desc limit 1").fetchone()
    assert row[0] == 9 and "insurance_squeeze" in row[1]      # 10 x confidence 0.9


# ---- sample owner layer -----------------------------------------------------------------------------
def test_sample_owner_layer_is_labeled_idempotent_and_flows_to_scores(db):
    add_territory(db)
    for i, code in enumerate(["11", "17", "15"]):
        parcel(db, f"300000090{i}", code, n=i)
    client = load_client("kaiser-team")
    res = load_owner_layer(db, client, AS_OF, CFG)
    assert res["residential_parcels"] == 2 and res["owners_inserted"] == 2 and res["sales_inserted"] >= 2
    assert db.execute("select count(*) from owners where apn='3000000902'").fetchone()[0] == 0   # non-residential
    assert db.execute("select bool_and(is_sample and provider='sample' and as_of=%s) from owners",
                      (AS_OF,)).fetchone()[0]
    assert db.execute("select bool_and(is_sample and provider='sample') from sales_history").fetchone()[0]
    again = load_owner_layer(db, client, AS_OF, CFG)
    assert again["owners_inserted"] == 0 and again["sales_inserted"] == 0
    # a later as_of is a new row, never an update
    load_owner_layer(db, client, AS_OF + timedelta(days=1), CFG)
    assert db.execute("select count(*) from owners").fetchone()[0] == 4
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update owners set absentee = not absentee")
    run_score(db, CFG, AS_OF)
    assert all(r[4] for r in scores(db).values() if r[5])          # owner components => uses_sample_data


def test_owner_fields_feed_components_and_reason(db):
    add_territory(db)
    parcel(db, "3000001000")
    db.execute("insert into owners (apn, owner_name, owner_occupied, absentee, out_of_state, last_sale_date, "
               "mortgage_open, est_equity, provider, is_sample, as_of) values "
               "('3000001000','Sample Owner 1000',false,true,true,'1990-05-05',false,5000000,'sample',true,%s)",
               (AS_OF,))
    run_score(db, CFG, AS_OF)
    apn, score, recipes, reason, sample, comps = scores(db)["3000001000"]
    keys = {c["key"] for c in comps}
    assert {"owner:years_owned", "owner:out_of_state", "owner:mortgage_open_false"} <= keys and "owner:absentee" not in keys
    assert sample is True and "(sample data)" in reason and "Owned 36 years" in reason


# ---- permit rules -------------------------------------------------------------------------------------
def test_stalled_rule_90_days_groups_and_close_date():
    run = date(2026, 11, 18)
    exp = lambda days: run - timedelta(days=days)
    issue = date(2024, 1, 1)
    assert permit_rules.is_stalled("remodel_addition", issue, exp(91), None, "Issued", run)
    assert not permit_rules.is_stalled("remodel_addition", issue, exp(90), None, "Issued", run)
    assert not permit_rules.is_stalled("remodel_addition", issue, exp(200), date(2025, 1, 1), "Issued", run)
    assert not permit_rules.is_stalled("remodel_addition", issue, exp(200), None, "Closed", run)
    for g in ("adu", "demolition_lot_split"):
        assert permit_rules.is_stalled(g, issue, exp(200), None, "Issued", run)
    for g in ("pre_sale_prep", "solar_energy", "other"):
        assert not permit_rules.is_stalled(g, issue, exp(200), None, "Issued", run)
    # expired within the last 36 months only
    assert permit_rules.is_stalled("adu", issue, date(2023, 11, 18), None, "Issued", run)        # exactly 36 months
    assert not permit_rules.is_stalled("adu", issue, date(2023, 11, 17), None, "Issued", run)    # one day older


def test_adu_total_regroups_a_permit_as_adu():
    mapping = {"Combination Building Permit": "remodel_addition"}
    p = {"APPROVAL_TYPE": "Combination Building Permit", "APPROVAL_ADU_TOTAL": "1.0",
         "APPROVAL_ISSUE_DATE": "2026-01-01"}
    assert permit_rules.derive(p, "1", mapping, date(2026, 11, 18))[0]["group"] == "adu"
    p["APPROVAL_ADU_TOTAL"] = "0"
    assert permit_rules.derive(p, "1", mapping, date(2026, 11, 18))[0]["group"] == "remodel_addition"


def test_final_permit_map_is_reviewed_and_follows_the_rules():
    data = yaml.safe_load(permit_rules.MAP_PATH.read_text())
    assert data["status"] == "reviewed"
    m = data["approval_types"]
    assert m["Photovoltaic - SB 379"] == "solar_energy"
    assert m["Approval - Construction - Electrical Pmt - PV Combo"] == "solar_energy"
    assert m["Demolition Permit"] == "demolition_lot_split" and m["Parcel Map"] == "demolition_lot_split"
    assert m["Tentative Map"] == "demolition_lot_split" and m["Lot-Line Adjustment"] == "demolition_lot_split"
    assert m["No-Plan - Residential - Combination Mech/Elec/Plum"] == "pre_sale_prep"
    assert m["Traffic Control Permit"] == "other" and m["Encroachment Agreement"] == "other"
    assert m["Sign Permit"] == "other" and m["No-Plan - Nonresidential/Multifamily - Electrical"] == "other"
    assert set(m.values()) <= set(permit_rules.SIGNAL_GROUPS)


# ---- re-derivation and superseded_by --------------------------------------------------------------------
def _seed_permit(db, apn, aid, atype, signals):
    rid = run_id(db, "dev_permits")
    payload = {"APPROVAL_TYPE": atype, "APPROVAL_ISSUE_DATE": "2025-01-01", "APPROVAL_EXPIRE_DATE": "2025-06-01",
               "APPROVAL_STATUS": "Issued", "APPROVAL_ID": aid}
    db.execute("insert into raw_records (source_key, source_record_id, run_id, payload) values "
               "('dev_permits',%s,%s,%s)", (aid, rid, Jsonb(payload)))
    for stype, group, on in signals:
        db.execute(
            "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
            "run_id, confidence, match_method, details) values (%s,%s,%s,%s,'dev_permits',%s,%s,0.95,'apn',%s)",
            (apn, stype, group, on, aid, rid, Jsonb({"approval_type": atype})))


def test_rederive_supersedes_and_inserts_without_deleting(db, tmp_path):
    add_territory(db)
    for i in range(3):
        parcel(db, f"300000110{i}", n=i)
    # old (proposed-map) signals: Coastal Dev was remodel_addition; Electrical stalled while pre_sale_prep
    _seed_permit(db, "3000001100", "P1", "Coastal Development Permit",
                 [("permit_approved", "remodel_addition", date(2025, 1, 1)),
                  ("permit_stalled", "remodel_addition", date(2025, 6, 1))])
    _seed_permit(db, "3000001101", "P2", "Electrical Permit",
                 [("permit_approved", "pre_sale_prep", date(2025, 1, 1)),
                  ("permit_stalled", "pre_sale_prep", date(2025, 6, 1))])
    _seed_permit(db, "3000001102", "P3", "Building Permit",                      # unchanged
                 [("permit_approved", "remodel_addition", date(2025, 1, 1)),
                  ("permit_stalled", "remodel_addition", date(2025, 6, 1))])
    final = tmp_path / "map.yaml"
    final.write_text(yaml.safe_dump({"status": "reviewed", "approval_types": {
        "Coastal Development Permit": "other", "Electrical Permit": "pre_sale_prep",
        "Building Permit": "remodel_addition"}}))
    before_total = db.execute("select count(*) from signals").fetchone()[0]
    rid = run_id(db, "permit_rederive")
    res = rederive(db, rid, date(2026, 11, 18), final)
    live = dict(((t, g, a), 1) for t, g, a in db.execute(
        "select signal_type, signal_group, apn from signals where superseded_by is null"))
    assert live == {("permit_approved", "other", "3000001100"): 1,         # regrouped
                    ("permit_approved", "pre_sale_prep", "3000001101"): 1,  # approved unchanged, stalled retired
                    ("permit_approved", "remodel_addition", "3000001102"): 1,
                    ("permit_stalled", "remodel_addition", "3000001102"): 1}
    assert res["superseded"] == 3 and res["inserted"] == 1
    # nothing was deleted: old rows are still there, stamped with the run that superseded them
    assert db.execute("select count(*) from signals").fetchone()[0] == before_total + 1
    assert db.execute("select count(*) from signals where superseded_by=%s", (rid,)).fetchone()[0] == 3
    new = db.execute("select details from signals where run_id=%s and signal_type='permit_approved' "
                     "and signal_group='other'", (rid,)).fetchone()[0]
    assert new["rederived"] is True and new["previous_group"] == "remodel_addition"
    # rerunning changes nothing
    res2 = rederive(db, run_id(db, "permit_rederive"), date(2026, 11, 18), final)
    assert res2["superseded"] == 0 and res2["inserted"] == 0
    assert res["before"][("permit_stalled", "pre_sale_prep")] == 1 and ("permit_stalled", "pre_sale_prep") not in res["after"]


def test_signals_stay_append_only_except_superseded_by(db):
    add_territory(db)
    parcel(db, "3000001200")
    sid = add_signal(db, "3000001200", "tax_default")
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update signals set confidence = 0.1 where id=%s", (sid,))
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("delete from signals where id=%s", (sid,))
    rid = run_id(db)
    db.execute("update signals set superseded_by=%s where id=%s", (rid, sid))
    with pytest.raises(psycopg.errors.RestrictViolation):                  # cannot be changed again
        db.execute("update signals set superseded_by=null where id=%s", (sid,))
    with pytest.raises(psycopg.errors.RestrictViolation):                  # not combined with another change
        sid2 = add_signal(db, "3000001200", "tax_default", on=date(2020, 1, 1))
        db.execute("update signals set superseded_by=%s, confidence=0.1 where id=%s", (rid, sid2))


# ---- checkpoint corrections ---------------------------------------------------------------------------
def _map_file(tmp_path, types, residential=(), name="map.yaml"):
    f = tmp_path / name
    f.write_text(yaml.safe_dump({"status": "reviewed", "approval_types": types,
                                 "residential_remodel_types": list(residential)}))
    return f


def _live(db):
    return sorted(db.execute("select apn, signal_type, signal_group from signals where superseded_by is null"))


def test_discretionary_types_become_remodel_only_when_the_record_is_residential(db, tmp_path):
    add_territory(db)
    parcel(db, "3000001300", "11", n=0)                  # residential parcel
    parcel(db, "3000001301", "7", n=1)                   # commercial parcel
    parcel(db, "3000001302", "7", n=2)                   # commercial parcel, record says residential
    for apn, aid in (("3000001300", "C1"), ("3000001301", "C2"), ("3000001302", "C3")):
        _seed_permit(db, apn, aid, "Coastal Development Permit", [("permit_approved", "other", date(2025, 1, 1))])
    rid = db.execute("select id from source_runs limit 1").fetchone()[0]
    db.execute("insert into raw_records (source_key, source_record_id, run_id, payload, fetched_at) values "
               "('dev_permits','C3',%s,%s, now() + interval '1 second')",
               (rid, Jsonb({"APPROVAL_TYPE": "Coastal Development Permit", "APPROVAL_ISSUE_DATE": "2025-01-01",
                            "PROJECT_TYPE": "Project - Residential - Remodel"})))
    f = _map_file(tmp_path, {"Coastal Development Permit": "other"}, ["Coastal Development Permit"])
    rederive(db, run_id(db, "permit_rederive"), date(2026, 11, 18), f)
    assert [r for r in _live(db) if r[1] == "permit_approved"] == [
        ("3000001300", "permit_approved", "remodel_addition"),
        ("3000001301", "permit_approved", "other"),
        ("3000001302", "permit_approved", "remodel_addition")]
    # a type that is not listed never moves, residential or not
    g = permit_rules.group_for("Grading Permit", 0, {"Grading Permit": "other"}, True, {"Coastal Development Permit"})
    assert g == "other"


def test_stalled_older_than_36_months_is_retired_by_rederive(db, tmp_path):
    add_territory(db)
    parcel(db, "3000001400")
    rid0 = run_id(db, "dev_permits")
    payload = {"APPROVAL_TYPE": "Building Permit", "APPROVAL_ISSUE_DATE": "2021-01-01",
               "APPROVAL_EXPIRE_DATE": "2022-01-01", "APPROVAL_STATUS": "Issued"}
    db.execute("insert into raw_records (source_key, source_record_id, run_id, payload) values "
               "('dev_permits','S1',%s,%s)", (rid0, Jsonb(payload)))
    for t, d in (("permit_approved", date(2021, 1, 1)), ("permit_stalled", date(2022, 1, 1))):
        db.execute("insert into signals (apn, signal_type, signal_group, signal_date, source_key, "
                   "source_record_id, run_id, confidence, match_method) values "
                   "('3000001400',%s,'remodel_addition',%s,'dev_permits','S1',%s,0.95,'apn')", (t, d, rid0))
    f = _map_file(tmp_path, {"Building Permit": "remodel_addition"})
    res = rederive(db, run_id(db, "permit_rederive"), date(2026, 11, 18), f)
    assert _live(db) == [("3000001400", "permit_approved", "remodel_addition")]
    assert res["superseded"] == 1 and res["inserted"] == 0
    assert db.execute("select count(*) from signals where signal_type='permit_stalled'").fetchone()[0] == 1  # kept


def test_a_type_mapped_back_to_a_former_group_gets_a_live_signal(db, tmp_path):
    add_territory(db)
    parcel(db, "3000001500")
    _seed_permit(db, "3000001500", "R1", "Electrical Permit", [("permit_approved", "pre_sale_prep", date(2025, 1, 1))])
    to_other = _map_file(tmp_path, {"Electrical Permit": "other"}, name="a.yaml")
    back = _map_file(tmp_path, {"Electrical Permit": "pre_sale_prep"}, name="b.yaml")
    rederive(db, run_id(db, "permit_rederive"), date(2026, 11, 18), to_other)
    assert _live(db) == [("3000001500", "permit_approved", "other")]
    res = rederive(db, run_id(db, "permit_rederive"), date(2026, 11, 18), back)
    assert _live(db) == [("3000001500", "permit_approved", "pre_sale_prep")]       # live again
    assert res["inserted"] == 1 and res["superseded"] == 1
    rederive(db, run_id(db, "permit_rederive"), date(2026, 11, 18), to_other)       # and back again
    assert _live(db) == [("3000001500", "permit_approved", "other")]
    assert db.execute("select count(*) from signals").fetchone()[0] == 4          # history kept, nothing deleted


# ---- latest_scores view ------------------------------------------------------------------------------
def test_latest_scores_view_returns_one_latest_row_per_parcel(db):
    add_territory(db)
    for i in range(2):
        parcel(db, f"300000160{i}", n=i)
    add_signal(db, "3000001600", "tax_default", on=AS_OF)
    run_score(db, CFG, AS_OF, datetime(2026, 11, 1, tzinfo=timezone.utc))
    add_signal(db, "3000001601", "tax_default", on=AS_OF)
    run_score(db, CFG, AS_OF, datetime(2026, 11, 2, tzinfo=timezone.utc))
    assert db.execute("select count(*) from scores").fetchone()[0] == 4
    rows = db.execute("select apn, score, scored_at from latest_scores order by apn").fetchall()
    assert [r[0] for r in rows] == ["3000001600", "3000001601"]
    assert all(r[2] == datetime(2026, 11, 2, tzinfo=timezone.utc) for r in rows)
    assert rows[1][1] > 0
    opts = db.execute("select reloptions from pg_class where relname='latest_scores'").fetchone()[0]
    assert "security_invoker=true" in opts


# ---- builder_bait lot-size medians ---------------------------------------------------------------------
def test_builder_bait_needs_a_lot_1_5x_the_area_median_and_the_medians_are_reported(db, tmp_path):
    add_territory(db)
    lots = {"3000001700": 4000, "3000001701": 4000, "3000001702": 4000, "3000001703": 10000, "3000001704": 5900}
    for i, (apn, lot) in enumerate(lots.items()):
        parcel(db, apn, n=i)
        db.execute("update parcels set lot_sqft=%s where apn=%s", (lot, apn))
        add_signal(db, apn, "sb9_lot_split_estimate", "upzoning", on=AS_OF)
        db.execute("insert into owners (apn, last_sale_date, provider, is_sample, as_of) values "
                   "(%s,'1990-01-01','sample',true,%s)", (apn, AS_OF))
    parcel(db, "3000001705", "7", n=9)                               # non-residential: not in the median
    db.execute("update parcels set lot_sqft=900000 where apn='3000001705'")
    s = run_score(db, CFG, AS_OF, report_dir=tmp_path)
    assert s["area_median_lot_sqft"] == {"La Jolla": 4000.0}
    hits = {r[0] for r in db.execute("select apn from scores where 'builder_bait' = any(recipe_matches)")}
    assert hits == {"3000001703"}                                     # 10000 >= 6000; 5900 < 6000
    report = (tmp_path / "scoring_report.md").read_text()
    assert "| La Jolla | 4000.0 | 6000.0 |" in report and "1.5" in report
