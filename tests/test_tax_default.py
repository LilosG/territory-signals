from datetime import date

from helpers import FIXTURES, add_parcel, add_territory, all_text, run
from territory.sources.tax_default import parse_pdf

PDF = FIXTURES / "tax_default_fixture.pdf"


def test_pdf_parsing_reads_both_columns():
    records, power_date = parse_pdf(PDF)
    assert len(records) == 6 and power_date == date(2026, 7, 1)
    by_apn = {r["apn"]: r for r in records}
    assert by_apn["3461201100"]["amount_to_redeem"] == 46587.39
    assert by_apn["3461201100"]["situs_text"] == "2356 CALLE DEL ORO"
    assert by_apn["3504004715"]["assessee_estate"] is True
    assert by_apn["3500701802"]["assessee_trust"] is True


def _setup(db):
    add_territory(db)
    for i, apn in enumerate(["3461201100", "3500701802", "3504004715"]):   # 3 of the 6 are in the territory
        add_parcel(db, apn, -117.25 + i * 0.01, 32.85)


def test_signals_by_apn_and_names_not_stored(db, tmp_path):
    _setup(db)
    out = run("tax_default", local_files={"tax_default": PDF}, report_dir=tmp_path)
    assert out.status == "success", out.error
    assert (out.rows_fetched, out.rows_matched, out.rows_unmatched, out.signals_written) == (3, 3, 0, 3)
    rows = db.execute("select distinct match_method, signal_type, signal_date, confidence from signals").fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("apn", "tax_default", date(2026, 7, 1))]
    assert "TEST OWNER" not in all_text(db, "select payload from raw_records")
    assert "TEST OWNER" not in all_text(db, "select details from signals")
    assert out.extra["excluded: not a territory parcel"] == 3


def test_rerun_does_not_duplicate(db, tmp_path):
    _setup(db)
    run("tax_default", local_files={"tax_default": PDF}, report_dir=tmp_path)
    assert run("tax_default", local_files={"tax_default": PDF}, report_dir=tmp_path).signals_written == 0
    assert db.execute("select count(*) from signals").fetchone()[0] == 3
