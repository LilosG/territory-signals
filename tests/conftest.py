import os
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipelines"))


TEST_DB = "territory_test"
MIGRATIONS = ROOT / "supabase" / "migrations"
WORKING_URL = os.environ.get("SUPABASE_DB_URL") or "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def _url_for(dbname: str) -> str:
    return WORKING_URL.rsplit("/", 1)[0] + "/" + dbname


def _working_db_name() -> str:
    return WORKING_URL.rsplit("/", 1)[1].split("?")[0]


def _row_counts(url: str) -> dict[str, int] | None:
    """Exact row count of every public table, or None if the database is unreachable."""
    try:
        with psycopg.connect(url, autocommit=True) as c:
            tables = [r[0] for r in c.execute(
                "select tablename from pg_tables where schemaname='public' order by 1")]
            return {t: c.execute(f'select count(*) from public."{t}"').fetchone()[0] for t in tables}
    except psycopg.OperationalError:
        return None


# Snapshot of the working database taken before the suite touches anything.
WORKING_COUNTS_BEFORE = _row_counts(WORKING_URL)


def _drop_test_db(admin) -> None:
    admin.execute(
        "select pg_terminate_backend(pid) from pg_stat_activity where datname = %s and pid <> pg_backend_pid()",
        (TEST_DB,))
    admin.execute(f'drop database if exists "{TEST_DB}"')


@pytest.fixture(scope="session")
def migrated_db():
    """Create a separate database (territory_test) on the local Postgres, apply every
    migration to it, point the pipelines at it, and drop it at the end. The working
    database is never reset or written by tests."""
    assert _working_db_name() != TEST_DB
    with psycopg.connect(WORKING_URL, autocommit=True) as admin:
        _drop_test_db(admin)
        admin.execute(f'create database "{TEST_DB}"')
    test_url = _url_for(TEST_DB)
    with psycopg.connect(test_url, autocommit=True) as c:
        c.execute("create schema if not exists extensions")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            c.execute(path.read_text(encoding="utf-8"))
    previous = os.environ.get("SUPABASE_DB_URL")
    os.environ["SUPABASE_DB_URL"] = test_url
    yield True
    if previous is None:
        os.environ.pop("SUPABASE_DB_URL", None)
    else:
        os.environ["SUPABASE_DB_URL"] = previous
    with psycopg.connect(WORKING_URL, autocommit=True) as admin:
        _drop_test_db(admin)


def pytest_sessionfinish(session, exitstatus):
    """Final guard, after the test database is dropped: the working database must
    have exactly the row counts it had before the suite started."""
    after = _row_counts(WORKING_URL)
    if WORKING_COUNTS_BEFORE is not None and after != WORKING_COUNTS_BEFORE:
        print(f"\nFATAL: working database row counts changed during the test run\n"
              f"before={WORKING_COUNTS_BEFORE}\nafter={after}")
        session.exitstatus = 1


@pytest.fixture
def conn(migrated_db):
    from territory.db import connect

    with connect() as c:
        yield c
        c.rollback()


TRUNCATE_ALL = (
    "truncate signals, raw_records, source_runs, owners, sales_history, scores, suppressions, "
    "outreach, outcomes, stage_events, ai_outputs, ai_task_runs, api_usage_log, backtest_runs, "
    "parcel_portfolios, parcels, neighborhoods restart identity cascade"
)


@pytest.fixture
def db(migrated_db):
    """Autocommit connection to a clean database. Pipeline runs open their own
    connections and commit, so tests that run them start from truncated tables
    (TRUNCATE is not blocked by the append-only triggers)."""
    from territory.db import connect

    with connect(autocommit=True) as c:
        # Hard guard: never truncate anything but the test database.
        assert c.execute("select current_database()").fetchone()[0] == TEST_DB
        c.execute(TRUNCATE_ALL)
        yield c
        c.execute(TRUNCATE_ALL)
