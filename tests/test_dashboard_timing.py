"""Phase 5D: every new dashboard view and function answers in under 500 ms for a team member.

Timed against the LOCAL working database (it has the real ~26k scored parcels; the empty test database would prove
nothing). Everything is read-only and runs in a rolled-back transaction as the `authenticated` role with a team
member's JWT claims, the way PostgREST calls it. Skipped when the local database or its data is not there.
"""
import json
import time

import psycopg
import pytest

import conftest

LIMIT_MS = 500

QUERIES = {
    "scored_parcels view": "select count(*) from scored_parcels where score >= 30",
    "scored_parcels by neighborhood": "select * from scored_parcels where neighborhood = 'La Jolla' order by score desc limit 25",
    "outreach_queue view": "select * from outreach_queue limit 25",
    "share_links_active view": "select * from share_links_active limit 25",
    "source_latest view": "select * from source_latest",
    "nav_counts": "select nav_counts(null)",
    "nav_counts (territory)": "select nav_counts('Pacific Beach')",
    "leads_list": "select * from leads_list(null, null, null, 20, 0)",
    "leads_list (territory)": "select * from leads_list('La Jolla', null, null, 20, 0)",
    "recipe_summary": "select * from recipe_summary(null)",
    "recipe_summary (territory)": "select * from recipe_summary('Mission Beach')",
    "recipe_top_leads": "select * from recipe_top_leads(null, 5)",
    "off_market_inventory": "select * from off_market_inventory(null, null, 'lot', 25, 0)",
    "off_market_inventory (builder bait)": "select * from off_market_inventory('La Jolla', 'builder_bait', 'score', 25, 0)",
    "search_leads (address)": "select * from search_leads('la jolla sh', null, 8)",
    "search_leads (apn)": "select * from search_leads('358070', null, 8)",
    "today_stats": "select * from today_stats(null)",
    "recent_signals": "select * from recent_signals(null, 14, 5)",
    "funnel_by agent": "select * from funnel_by('agent', null)",
    "funnel_by recipe": "select * from funnel_by('recipe', null)",
    "coverage_weekly": "select * from coverage_weekly(12, null)",
}


@pytest.fixture(scope="module")
def team_db():
    try:
        conn = psycopg.connect(conftest.WORKING_URL, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("local database not reachable")
    with conn:
        try:
            email = conn.execute("select email from team_members order by created_at limit 1").fetchone()
            rows = conn.execute("select count(*) from private.scored_parcels").fetchone()[0]
        except psycopg.Error:
            pytest.skip("working database has no 5D migration yet")
        if not email or rows < 1000:
            pytest.skip("working database has no team member or scored parcels")
        yield conn, email[0]


def run_as_member(conn, email, sql):
    conn.execute("begin")
    try:
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps({"email": email}),))
        t = time.perf_counter()
        rows = conn.execute(sql).fetchall()
        return (time.perf_counter() - t) * 1000, rows
    finally:
        conn.execute("rollback")


@pytest.mark.parametrize("name", list(QUERIES))
def test_query_is_fast_for_a_team_member(team_db, name):
    conn, email = team_db
    run_as_member(conn, email, QUERIES[name])                      # warm the cache, like a user's second click
    times = [run_as_member(conn, email, QUERIES[name])[0] for _ in range(3)]
    assert max(times) < LIMIT_MS, f"{name}: {[round(t) for t in times]} ms (limit {LIMIT_MS})"


def test_every_view_returns_rows_to_a_team_member(team_db):
    conn, email = team_db
    _, rows = run_as_member(conn, email, QUERIES["scored_parcels view"])
    assert rows[0][0] > 0


def test_non_team_user_reads_nothing_from_the_new_views(team_db):
    conn, _ = team_db
    for sql in ("select count(*) from scored_parcels", "select count(*) from outreach_queue", "select count(*) from share_links_active"):
        _, rows = run_as_member(conn, "stranger@example.test", sql)
        assert rows[0][0] == 0, sql
