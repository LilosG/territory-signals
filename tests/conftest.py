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
