"""Pipelines refuse any non-local database host unless --cloud is passed."""
import subprocess
import sys
from pathlib import Path

import pytest

from territory import db

PIPELINES = Path(__file__).resolve().parents[1] / "pipelines"
CLOUD = "postgresql://postgres:x@db.example.supabase.co:5432/postgres?sslmode=require"


@pytest.fixture(autouse=True)
def _reset():
    db.allow_cloud(False)
    yield
    db.allow_cloud(False)


def test_cloud_host_is_refused_and_named(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", CLOUD)
    with pytest.raises(SystemExit) as e:
        db.connect()
    assert "db.example.supabase.co" in str(e.value) and "--cloud" in str(e.value)


def test_local_hosts_pass_the_guard(monkeypatch):
    for u in ("postgresql://postgres:postgres@127.0.0.1:54322/postgres", "postgresql://u@localhost/db"):
        monkeypatch.setenv("SUPABASE_DB_URL", u)
        db.check_target()
    monkeypatch.delenv("SUPABASE_DB_URL")
    db.check_target()


def test_allow_cloud_lifts_the_guard(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", CLOUD)
    db.allow_cloud(True)
    db.check_target()


@pytest.mark.parametrize("module,args", [
    ("territory.score", ["--client", "kaiser-team"]),
    ("territory.permit_rederive", ["--client", "kaiser-team"]),
    ("territory.outreach", ["--client", "kaiser-team"]),
    ("territory.run", ["--client", "kaiser-team", "--only-ai", "--tasks", "weekly_brief"]),
])
def test_entry_points_exit_with_host_error(module, args, monkeypatch):
    env = {**__import__("os").environ, "SUPABASE_DB_URL": CLOUD}
    r = subprocess.run([sys.executable, "-m", module, *args], cwd=PIPELINES, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "db.example.supabase.co" in (r.stderr + r.stdout) and "--cloud" in (r.stderr + r.stdout)
