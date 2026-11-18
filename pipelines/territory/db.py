"""Postgres connection. Reads SUPABASE_DB_URL; defaults to the local Supabase stack."""
from __future__ import annotations

import os

import psycopg

LOCAL_DEFAULT_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def db_url() -> str:
    return os.environ.get("SUPABASE_DB_URL") or LOCAL_DEFAULT_DB_URL


def connect(**kwargs) -> psycopg.Connection:
    return psycopg.connect(db_url(), **kwargs)
