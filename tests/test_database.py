import json

TABLES = [
    "neighborhoods", "parcels", "source_runs", "raw_records", "signals", "owners",
    "sales_history", "scores", "suppressions", "outreach", "outcomes", "team_members",
]


def test_migration_applies_on_fresh_database(migrated_db):
    assert migrated_db


def test_every_table_exists_with_rls(conn):
    rows = conn.execute(
        "select c.relname, c.relrowsecurity from pg_class c "
        "join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r'"
    ).fetchall()
    found = dict(rows)
    for t in TABLES:
        assert t in found, f"missing table {t}"
    for t, rls in found.items():
        assert rls, f"RLS not enabled on {t}"


def test_insert_parcel_signal_score_roundtrip(conn):
    conn.execute(
        "insert into parcels (apn, situs_address, zip, planning_area, source_key) "
        "values ('3000000001', '1 Test St', '92037', 'La Jolla', 'test')"
    )
    run_id = conn.execute(
        "insert into source_runs (source_key, status) values ('test', 'success') returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into signals (apn, signal_type, signal_group, source_key, source_record_id, "
        "run_id, confidence, match_method, is_sample, details) "
        "values ('3000000001', 'permit', 'construction', 'test', 'r1', %s, 0.9, 'apn', true, %s)",
        (run_id, json.dumps({"k": "v"})),
    )
    conn.execute(
        "insert into scores (apn, score, components, recipe_matches, model_version) "
        "values ('3000000001', 72, %s, %s, 'v0')",
        (json.dumps({"permit": 40}), ["recipe_a"]),
    )
    sig = conn.execute(
        "select signal_type, confidence, match_method, is_sample, details from signals "
        "where apn = '3000000001'"
    ).fetchone()
    assert sig[0] == "permit" and float(sig[1]) == 0.9 and sig[2] == "apn" and sig[3] is True
    assert sig[4] == {"k": "v"}
    score = conn.execute("select score, recipe_matches from scores where apn = '3000000001'").fetchone()
    assert score == (72, ["recipe_a"])
