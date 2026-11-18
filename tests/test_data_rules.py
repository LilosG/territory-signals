"""CLAUDE.md data rules, checked across every adapter at once."""
import pandas as pd

from helpers import FIXTURES, add_parcel, add_territory, run
from test_dev_permits import MAP, _setup as setup_permits
from test_tax_default import PDF
from test_upzoning_estimate import write_transit, square


def test_every_signal_has_provenance_fields(db, tmp_path):
    setup_permits(db)                                   # also creates the territory
    df = pd.read_csv(FIXTURES / "stro_licenses_fixture.csv", dtype=str)
    for i, r in enumerate(df.itertuples()):
        if r.license_id != "STR-OUTSIDE":
            add_parcel(db, f"{3100000000 + i}", float(r.longitude), float(r.latitude))
    for i, apn in enumerate(["3461201100", "3500701802", "3504004715"]):
        add_parcel(db, apn, -117.21 + i * 0.001, 32.80)
    add_parcel(db, "9000000001", 0, 0, zoning="RS-1-7", lot=6000, geom=square(0, 20000))

    runs = [
        run("stro_licenses", local_files={"stro_licenses": FIXTURES / "stro_licenses_fixture.csv"}, report_dir=tmp_path),
        run("dev_permits", local_files={"dev_permits": [FIXTURES / "approvals_issued_fixture.csv"],
                                        "permit_signal_map": MAP}, report_dir=tmp_path),
        run("tax_default", local_files={"tax_default": PDF}, report_dir=tmp_path),
        run("upzoning_estimate", local_files=write_transit(tmp_path), report_dir=tmp_path),
    ]
    assert [r.status for r in runs] == ["success"] * 4, [r.error for r in runs]
    assert db.execute("select count(*) from signals").fetchone()[0] > 20
    bad = db.execute(
        "select count(*) from signals where source_key is null or source_key = '' or source_record_id is null "
        "or source_record_id = '' or confidence is null or match_method is null or match_method = ''").fetchone()[0]
    assert bad == 0
    assert db.execute("select count(*) from signals where is_estimate and source_key <> 'upzoning_estimate'").fetchone()[0] == 0
    assert db.execute("select count(*) from signals where source_key = 'upzoning_estimate' and not is_estimate").fetchone()[0] == 0
    assert db.execute("select count(*) from raw_records where run_id is null").fetchone()[0] == 0
    # every run has a source_runs row with counts
    assert db.execute("select count(*) from source_runs where status='success' and rows_fetched is not null "
                      "and rows_matched is not null and rows_unmatched is not null").fetchone()[0] == 4
