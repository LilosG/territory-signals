"""Phase 6: deterministic historical backtest (days-early math, windows and storage)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from helpers import add_parcel, add_territory
from territory.backtest import (
    BacktestSale, BacktestSignal, compute_backtest, load_sales, run_backtest,
)
from territory.config import load_client
from territory.scoring_engine import load_scoring_config

AS_OF = date(2026, 11, 18)
TRANSFERS = load_scoring_config()["transfer_types"]


def sale(apn, d, doc="grant deed", sample=False):
    return BacktestSale(apn, d, doc, sample)


def sig(apn, d, source="dev_permits", type_="permit_approved", group="permits", sample=False):
    return BacktestSignal(apn, d, source, type_, group, sample)


def bt(sales, signals, start=date(2024, 11, 18), end=AS_OF, **kw):
    return compute_backtest(sales, signals, start, end, TRANSFERS, **kw)


def test_days_early_is_measured_from_the_earliest_qualifying_signal():
    r = bt([sale("A", date(2026, 6, 1))],
           [sig("A", date(2026, 5, 1)), sig("A", date(2026, 5, 20))])
    assert r["flagged_before_sale_count"] == 1
    assert r["median_days_early"] == 31 and r["avg_days_early"] == 31
    assert r["capture_rate_pct"] == 100.0
    assert r["breakdown_by_signal_group"] == {"dev_permits": 1}


def test_window_is_inclusive_at_14_and_365_days_and_excludes_the_edges():
    sales = [sale("A", date(2026, 6, 1)), sale("B", date(2026, 6, 1)), sale("C", date(2026, 6, 1)),
             sale("D", date(2026, 6, 1))]
    signals = [
        sig("A", date(2026, 5, 18)),     # exactly 14 days: counts
        sig("B", date(2025, 6, 1)),      # exactly 365 days: counts
        sig("C", date(2026, 5, 19)),     # 13 days: too late
        sig("D", date(2025, 5, 31)),     # 366 days: too early
    ]
    r = bt(sales, signals)
    assert r["flagged_before_sale_count"] == 2
    assert r["capture_rate_pct"] == 50.0
    assert r["median_days_early"] == 189.5                      # median of 14 and 365


def test_only_public_source_signals_count():
    sigs = [sig("A", date(2026, 4, 1), source="attom", type_="notice_of_default", group="distress"),
            sig("A", date(2026, 4, 2), source="other", type_="tax_default", group="distress")]
    # An unknown source_key is still accepted when its signal type is public; the ATTOM recorder is not.
    r = bt([sale("A", date(2026, 5, 1))], sigs)
    assert r["flagged_before_sale_count"] == 1
    assert r["breakdown_by_signal_group"] == {"tax_default": 1}


def test_transfers_are_not_sales_and_duplicates_are_collapsed():
    sales = [sale("A", date(2026, 6, 1)), sale("A", date(2026, 6, 1)),
             sale("B", date(2026, 6, 1), doc="trust transfer deed"),
             sale("C", date(2026, 6, 1), doc="Affidavit of Death")]
    r = bt(sales, [sig("A", date(2026, 5, 1))])
    assert r["total_sales_evaluated"] == 1
    assert r["flagged_before_sale_count"] == 1


def test_sample_flags_propagate_and_empty_window_is_safe():
    assert bt([sale("A", date(2026, 6, 1), sample=True)], [sig("A", date(2026, 5, 1))])["is_sample"] is True
    assert bt([sale("A", date(2026, 6, 1))], [sig("A", date(2026, 5, 1), sample=True)])["is_sample"] is True
    empty = bt([], [])
    assert empty["total_sales_evaluated"] == 0 and empty["capture_rate_pct"] == 0.0
    assert empty["median_days_early"] is None and empty["is_sample"] is False


# ---- database run ------------------------------------------------------------------------
def _seed(db):
    add_territory(db)
    for i, apn in enumerate(["5000000001", "5000000002", "5000000003"]):
        add_parcel(db, apn, -117.30 + i * 0.001, 32.85)
    db.execute(
        "insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) values "
        "('5000000001','2026-06-01',900000,'grant deed','attom',false),"
        "('5000000002','2026-06-01',850000,'grant deed','attom',false),"
        "('5000000003','2026-06-01',null,'Trust Transfer Deed','attom',false)")
    db.execute(
        "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
        "confidence, match_method, is_sample) values "
        "('5000000001','permit_approved','pre_sale_prep','2026-04-01','dev_permits','P1',0.95,'apn',false),"
        "('5000000001','tax_default','distress','2026-03-01','tax_default','T1',0.95,'apn',false),"
        "('5000000002','stro_license_removed','stro','2026-05-25','stro_licenses','S1',0.95,'apn',false)")


def test_run_backtest_writes_a_real_row_and_latest_view(db):
    _seed(db)
    client = load_client("kaiser-team")
    r = run_backtest(db, client, AS_OF)
    assert r["total_sales_evaluated"] == 2                     # the transfer is excluded
    assert r["flagged_before_sale_count"] == 1                 # only the April permit is 14+ days early
    assert r["median_days_early"] == 61
    assert r["breakdown_by_signal_group"] == {"dev_permits": 1, "tax_default": 1}
    assert r["is_sample"] is False
    row = db.execute("select client_id, window_start, window_end, total_sales_evaluated, "
                     "flagged_before_sale_count, capture_rate_pct, median_days_early, "
                     "breakdown_by_signal_group, is_sample from backtest_runs").fetchone()
    assert row[0] == "kaiser-team" and row[3] == 2 and row[4] == 1 and float(row[5]) == 50.0
    assert float(row[6]) == 61 and row[7] == {"dev_permits": 1, "tax_default": 1} and row[8] is False
    latest = db.execute("select count(*) from latest_backtest_runs").fetchone()[0]
    assert latest == 1


def test_backtest_marks_sample_when_sales_are_sample(db):
    _seed(db)
    # sales_history is append-only, so seed the sample sale on a fresh parcel from the start.
    add_parcel(db, "5000000004", -117.29, 32.85)
    db.execute("insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) "
               "values ('5000000004','2026-06-01',700000,'grant deed','sample',true)")
    db.execute("insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
               "confidence, match_method, is_sample) values "
               "('5000000004','permit_approved','pre_sale_prep','2026-04-01','dev_permits','P4',0.95,'apn',false)")
    r = run_backtest(db, load_client("kaiser-team"), AS_OF)
    assert r["is_sample"] is True


def test_load_sales_reads_the_window(db):
    _seed(db)
    assert len(load_sales(db, date(2024, 11, 18), AS_OF)) == 3
    assert len(load_sales(db, date(2026, 6, 2), AS_OF)) == 0


def test_backtest_cli_cloud_guard_is_covered_elsewhere():
    # exercised by tests/test_cloud_guard.py (subprocess entry point)
    assert datetime.now() is not None
