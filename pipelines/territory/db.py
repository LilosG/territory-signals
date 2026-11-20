"""Postgres connection. Reads SUPABASE_DB_URL; defaults to the local Supabase stack."""
from __future__ import annotations

import os
import sys

import psycopg
import psycopg.conninfo

LOCAL_DEFAULT_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_CLOUD_OK = False


class CloudGuardError(SystemExit):
    """Raised (as a clean exit) when a command would use a non-local database without --cloud."""


def allow_cloud(on: bool = True) -> None:
    global _CLOUD_OK
    _CLOUD_OK = on


def _strip_cloud_flag() -> None:
    """Every entry point accepts --cloud. It is removed from sys.argv here (db is imported before argparse runs)."""
    if "--cloud" in sys.argv:
        sys.argv[:] = [a for a in sys.argv if a != "--cloud"]
        allow_cloud(True)


_strip_cloud_flag()


def db_host(url: str | None = None) -> str:
    return (psycopg.conninfo.conninfo_to_dict(url or db_url()).get("host") or "localhost")


def db_url() -> str:
    return os.environ.get("SUPABASE_DB_URL") or LOCAL_DEFAULT_DB_URL


def check_target() -> None:
    """Refuse any database host other than 127.0.0.1/localhost unless --cloud was passed."""
    host = db_host()
    if host not in LOCAL_HOSTS and not _CLOUD_OK:
        raise CloudGuardError(
            f"REFUSING to use database host '{host}': it is not local (127.0.0.1/localhost). "
            "Pass --cloud to confirm you mean the cloud database, or run with `env -u SUPABASE_DB_URL` for local.")


def connect(**kwargs) -> psycopg.Connection:
    check_target()
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
