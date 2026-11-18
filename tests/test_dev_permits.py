from pathlib import Path

import pandas as pd
import yaml

from helpers import FIXTURES, RUN_DATE, add_parcel, add_territory, all_text, run

FIXTURE = FIXTURES / "approvals_issued_fixture.csv"
MAP = Path(__file__).resolve().parents[1] / "config" / "permit_signal_map.yaml"
GROUPS = {"pre_sale_prep", "remodel_addition", "adu", "demolition_lot_split", "solar_energy", "other"}


def _setup(db):
    add_territory(db)
    df = pd.read_csv(FIXTURE, dtype=str)
    for i, r in enumerate(df.itertuples()):
        if i == 2:
            continue                                    # outside the territory
        lat, lon = r.GIS_LATITUDE, r.GIS_LONGITUDE
        if i == 1:                                      # address-only row: parcel elsewhere
            add_parcel(db, "3999999991", -117.2, 32.8, situs=r.GIS_ADDRESS)
        elif i == 0:                                    # blank APN, coordinates in the parcel
            add_parcel(db, "3999999990", float(lon), float(lat))
        else:
            add_parcel(db, r.GIS_APN, float(lon), float(lat))
    return df


def _run(tmp_path, **kw):
    return run("dev_permits", local_files={"dev_permits": [FIXTURE], "permit_signal_map": MAP},
               report_dir=tmp_path, **kw)


def test_profile_is_written_before_signals_and_lists_every_type(db, tmp_path):
    df = _setup(db)
    out = _run(tmp_path)
    assert out.status == "success", out.error
    prof = pd.read_csv(tmp_path / "permit_type_profile.csv")
    assert {"APPROVAL_TYPE", "PROJECT_TYPE"} <= set(prof.field)
    in_scope_types = set(df.drop(index=2).APPROVAL_TYPE)
    assert in_scope_types <= set(prof[prof.field == "APPROVAL_TYPE"].value)


def test_match_methods_and_scope(db, tmp_path):
    _setup(db)
    out = _run(tmp_path)
    assert out.rows_fetched == 13 and out.rows_matched == 13          # row 2 is outside the territory
    methods = dict(db.execute(
        "select match_method, count(*) from signals where signal_type='permit_approved' group by 1").fetchall())
    assert methods.get("spatial") == 1 and methods.get("address") == 1 and methods["apn"] >= 10
    assert db.execute("select count(*) from raw_records where payload->>'GIS_APN'='9999999999'").fetchone()[0] == 0


def test_permit_holder_is_dropped(db, tmp_path):
    _setup(db)
    assert _run(tmp_path).status == "success"
    assert "Test Holder" not in all_text(db, "select payload from raw_records")
    assert "APPROVAL_PERMIT_HOLDER" not in all_text(db, "select payload from raw_records")


def test_signal_groups_come_from_the_map_and_unknown_types_are_other(db, tmp_path):
    df = _setup(db)
    _run(tmp_path)
    mapping = yaml.safe_load(MAP.read_text())["approval_types"]
    rows = db.execute("select details->>'approval_type', signal_group, details->>'adu_total' from signals "
                      "where signal_type='permit_approved'").fetchall()
    for atype, group, adu in rows:
        # the map decides the group; APPROVAL_ADU_TOTAL > 0 regroups a permit as adu (Phase 3)
        assert group == ("adu" if adu and float(adu) > 0 else mapping.get(atype, "other"))
    assert ("Brand New Approval Type", "other") in [(r[0], r[1]) for r in rows]


def test_stalled_only_when_expired_and_not_closed(db, tmp_path):
    df = _setup(db)
    # Row 3 (Mechanical Pmt) expired 2025-01-10, never closed. In the shipped map it is
    # pre_sale_prep, and stalled only counts for remodel_addition / adu / demolition_lot_split.
    _run(tmp_path)
    assert db.execute("select count(*) from signals where signal_type='permit_stalled'").fetchone()[0] == 0
    remap = tmp_path / "map.yaml"
    remap.write_text(yaml.safe_dump({"status": "reviewed", "approval_types": {"Mechanical Pmt": "remodel_addition"}}))
    db.execute("truncate signals, raw_records, source_runs cascade")
    run("dev_permits", local_files={"dev_permits": [FIXTURE], "permit_signal_map": remap}, report_dir=tmp_path)
    stalled = db.execute("select source_record_id, signal_date, signal_group from signals "
                         "where signal_type='permit_stalled'").fetchall()
    assert [s[0] for s in stalled] == [df.APPROVAL_ID.iloc[3]]
    assert str(stalled[0][1]) == "2025-01-10" and stalled[0][2] == "remodel_addition"


def test_rerun_does_not_duplicate(db, tmp_path):
    _setup(db)
    _run(tmp_path)
    n = db.execute("select count(*) from signals").fetchone()[0]
    assert _run(tmp_path).signals_written == 0
    assert db.execute("select count(*) from signals").fetchone()[0] == n


def test_missing_map_fails_the_run_cleanly(db, tmp_path):
    _setup(db)
    out = run("dev_permits", local_files={"dev_permits": [FIXTURE], "permit_signal_map": tmp_path / "nope.yaml"},
              report_dir=tmp_path)
    assert out.status == "failed" and "nope.yaml" in out.error
    assert db.execute("select count(*) from raw_records").fetchone()[0] == 0


def test_shipped_map_is_reviewed_and_uses_known_groups():
    text = MAP.read_text()
    first = next(l for l in text.splitlines() if l.strip() and not l.startswith("#"))
    assert first.startswith("status: reviewed")
    data = yaml.safe_load(text)
    assert set(data["approval_types"].values()) <= GROUPS
