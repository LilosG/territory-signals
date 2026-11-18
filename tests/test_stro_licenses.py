from datetime import date, timedelta

import pandas as pd

from helpers import FIXTURES, RUN_DATE, add_parcel, add_territory, all_text, run
from territory.sources.stro_licenses import KEEP_COLUMNS

FIXTURE = FIXTURES / "stro_licenses_fixture.csv"


def _setup(db, path=FIXTURE):
    add_territory(db)
    df = pd.read_csv(path, dtype=str)
    for i, r in enumerate(df.itertuples()):
        if r.license_id == "STR-OUTSIDE":
            continue
        add_parcel(db, f"{3000000000 + i}", float(r.longitude), float(r.latitude))


def test_licenses_match_by_point_in_polygon(db, tmp_path):
    _setup(db)
    out = run("stro_licenses", local_files={"stro_licenses": FIXTURE}, report_dir=tmp_path)
    assert out.status == "success", out.error
    assert out.rows_fetched == 10 and out.rows_matched == 10 and out.rows_unmatched == 0
    rows = db.execute("select distinct match_method, signal_type, signal_date from signals").fetchall()
    assert rows == [("spatial", "stro_license_active", RUN_DATE)]
    assert db.execute("select count(*) from raw_records where source_record_id='STR-OUTSIDE'").fetchone()[0] == 0
    report = (tmp_path / "stro_licenses_match_report.md").read_text()
    assert "spatial" in report and "stro_licenses" in report


def test_host_names_and_phones_are_never_stored(db, tmp_path):
    _setup(db)
    assert run("stro_licenses", local_files={"stro_licenses": FIXTURE}, report_dir=tmp_path).status == "success"
    raw = all_text(db, "select payload from raw_records")
    sig = all_text(db, "select details from signals")
    for text in (raw, sig):
        for forbidden in ("Test Host", "Test Contact", "619-555", "host_contact_name",
                          "local_contact", "phone"):
            assert forbidden not in text
    keys = {k for (p,) in db.execute("select payload from raw_records").fetchall() for k in p}
    assert keys <= set(KEEP_COLUMNS) | {"status"}
    assert not (set(pd.read_csv(FIXTURE, nrows=0).columns) - set(KEEP_COLUMNS)) & keys


def test_rerun_same_day_does_not_duplicate_signals(db, tmp_path):
    _setup(db)
    kw = dict(local_files={"stro_licenses": FIXTURE}, report_dir=tmp_path)
    first = run("stro_licenses", **kw)
    n = db.execute("select count(*) from signals").fetchone()[0]
    second = run("stro_licenses", **kw)
    assert first.signals_written == 10 and second.signals_written == 0
    assert db.execute("select count(*) from signals").fetchone()[0] == n == 10


def test_first_run_is_baseline_then_removal_is_detected(db, tmp_path):
    _setup(db)
    first = run("stro_licenses", local_files={"stro_licenses": FIXTURE}, report_dir=tmp_path)
    assert first.extra["baseline"].startswith("first run")
    assert db.execute("select count(*) from signals where signal_type='stro_license_removed'").fetchone()[0] == 0

    df = pd.read_csv(FIXTURE, dtype=str)
    gone = df.license_id.iloc[2]
    shrunk = tmp_path / "stro_shrunk.csv"
    df[df.license_id != gone].to_csv(shrunk, index=False)
    tomorrow = RUN_DATE + timedelta(days=1)
    second = run("stro_licenses", run_date=tomorrow, local_files={"stro_licenses": shrunk}, report_dir=tmp_path)
    assert second.status == "success", second.error
    removed = db.execute(
        "select source_record_id, signal_date, match_method from signals "
        "where signal_type='stro_license_removed'").fetchall()
    assert removed == [(gone, tomorrow, "spatial")]
    # the removed license's apn is the one its active signal pointed at
    apns = db.execute("select count(distinct apn) from signals where source_record_id=%s", (gone,)).fetchone()[0]
    assert apns == 1
