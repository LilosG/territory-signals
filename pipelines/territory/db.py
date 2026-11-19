"""Postgres connection. Reads SUPABASE_DB_URL; defaults to the local Supabase stack."""
from __future__ import annotations

import os
import sys

import psycopg

LOCAL_DEFAULT_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def db_url() -> str:
    return os.environ.get("SUPABASE_DB_URL") or LOCAL_DEFAULT_DB_URL


def connect(**kwargs) -> psycopg.Connection:
    return psycopg.connect(db_url(), **kwargs)


def refresh_dashboard_aggregates() -> bool:
    """Rebuild the pre-computed tables behind /trends. Called after every data load.
    Never raises: the load is already committed, so a failure here is only reported
    (run `select private.refresh_dashboard_aggregates();` by hand to retry)."""
    try:
        with connect(autocommit=True) as conn:
            conn.execute("select private.refresh_dashboard_aggregates()")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not refresh dashboard aggregates: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False
