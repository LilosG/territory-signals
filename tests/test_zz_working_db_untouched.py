"""Runs last (file name sorts last): proves the suite did not touch the working database."""
import os

import conftest


def test_tests_run_against_the_test_database(migrated_db):
    assert os.environ["SUPABASE_DB_URL"].endswith("/" + conftest.TEST_DB)
    assert conftest._working_db_name() != conftest.TEST_DB


def test_working_database_row_counts_unchanged(migrated_db):
    before = conftest.WORKING_COUNTS_BEFORE
    if before is None:
        import pytest
        pytest.skip("working database not reachable")
    assert conftest._row_counts(conftest.WORKING_URL) == before
