import json

import psycopg
import pytest


def _seed(conn):
    conn.execute("insert into parcels (apn, source_key) values ('3000000001', 'test')")
    run_id = conn.execute("insert into source_runs (source_key, status) values ('test', 'success') returning id").fetchone()[0]
    conn.execute("insert into raw_records (source_key, source_record_id, run_id, payload) values ('test','r1',%s,%s)",
                 (run_id, json.dumps({"a": 1})))
    conn.execute(
        "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, run_id, "
        "confidence, match_method) values ('3000000001','t','g','2026-01-01','test','r1',%s,0.9,'apn')", (run_id,))
    conn.execute("insert into owners (apn, owner_name, provider, is_sample, as_of) "
                 "values ('3000000001','Sample Owner 0001','sample',true,'2026-01-01')")
    conn.execute("insert into sales_history (apn, sale_price, provider, is_sample) "
                 "values ('3000000001', 1, 'sample', true)")


@pytest.mark.parametrize("table,set_clause", [
    ("signals", "confidence = 0.1"), ("raw_records", "payload = '{}'::jsonb"),
    ("owners", "owner_name = 'x'"), ("sales_history", "sale_price = 2")])
def test_update_and_delete_are_rejected(conn, table, set_clause):
    _seed(conn)
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute(f"update {table} set {set_clause}")
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute(f"delete from {table}")
    assert conn.execute(f"select count(*) from {table}").fetchone()[0] == 1


def test_insert_is_still_allowed_and_other_tables_unaffected(conn):
    _seed(conn)
    conn.execute("update parcels set zoning = 'RS-1-7' where apn = '3000000001'")
    conn.execute("update source_runs set status = 'failed' where source_key = 'test'")


def test_signal_natural_key_blocks_duplicates(conn):
    _seed(conn)
    run_id = conn.execute("select id from source_runs limit 1").fetchone()[0]
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            conn.execute(
                "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, "
                "run_id, confidence, match_method) values ('3000000001','t','g','2026-01-01','test','r1',%s,0.5,'apn')",
                (run_id,))
    # a signal with no date is deduplicated too (NULLS NOT DISTINCT)
    ins = ("insert into signals (apn, signal_type, signal_group, source_key, source_record_id, run_id, "
           "confidence, match_method) values ('3000000001','t2','g','test','r9',%s,0.5,'apn')")
    conn.execute(ins, (run_id,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            conn.execute(ins, (run_id,))
