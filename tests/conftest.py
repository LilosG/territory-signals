import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipelines"))


@pytest.fixture(scope="session")
def migrated_db():
    """Reset the local database from migrations (requires `supabase start`)."""
    result = subprocess.run(
        ["supabase", "db", "reset"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, f"supabase db reset failed:\n{result.stdout}\n{result.stderr}"
    return True


@pytest.fixture
def conn(migrated_db):
    from territory.db import connect

    with connect() as c:
        yield c
        c.rollback()


TRUNCATE_ALL = (
    "truncate signals, raw_records, source_runs, owners, sales_history, scores, suppressions, "
    "outreach, outcomes, parcels, neighborhoods restart identity cascade"
)


@pytest.fixture
def db(migrated_db):
    """Autocommit connection to a clean database. Pipeline runs open their own
    connections and commit, so tests that run them start from truncated tables
    (TRUNCATE is not blocked by the append-only triggers)."""
    from territory.db import connect

    with connect(autocommit=True) as c:
        c.execute(TRUNCATE_ALL)
        yield c
        c.execute(TRUNCATE_ALL)
