"""Phase 5K: weekly orchestrator, Monday digest and VPS systemd kit."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from psycopg.types.json import Jsonb

from helpers import FIXTURES, RUN_DATE, add_parcel, add_territory, client
from territory import db, digest, weekly_run
from territory.config import load_client
from territory.llm.fake import FakeProvider
from territory.sources.dev_permits import clean_apn

ROOT = Path(__file__).resolve().parents[1]
PIPELINES = ROOT / "pipelines"
PERMIT_MAP = ROOT / "config" / "permit_signal_map.yaml"
SERVICE = ROOT / "deploy" / "vps" / "territory-weekly.service"
TIMER = ROOT / "deploy" / "vps" / "territory-weekly.timer"
INSTALL = ROOT / "deploy" / "vps" / "install.sh"

STRO = FIXTURES / "stro_licenses_fixture.csv"
PERMITS = FIXTURES / "approvals_issued_fixture.csv"
TAX = FIXTURES / "tax_default_fixture.pdf"
NEWS = ("This week brought steady activity across our neighborhoods, with homeowners pulling permits for everyday upgrades "
        "like new heating and cooling systems, fresh paint and plumbing work. Many of these projects keep homes comfortable and "
        "efficient for years to come. If you are curious what recent improvements mean for the value of your home, we are happy "
        "to share a simple, no-pressure summary of what is happening on your street and nearby.")


# ---------------------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------------------
def _transit_files(tmp_path: Path) -> dict[str, Path]:
    stops = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"stop_UID": "S1", "stop_name": "Test Station", "location_type": "1"},
         "geometry": {"type": "Point", "coordinates": [-117.27, 32.84]}}]}
    routes = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"route_id": "R1", "route_type": 0, "route_long_name": "Test Rail",
                                           "route_color": "000000"},
         "geometry": {"type": "LineString", "coordinates": [[-117.28, 32.83], [-117.26, 32.85]]}}]}
    sp, rp = tmp_path / "transit_stops.geojson", tmp_path / "transit_routes.geojson"
    sp.write_text(json.dumps(stops), encoding="utf-8")
    rp.write_text(json.dumps(routes), encoding="utf-8")
    return {"transit_stops": sp, "transit_routes": rp}


def _seed_weekly(db, tmp_path: Path) -> dict:
    """A small territory with real fixture records for every live source, one owner row per parcel and no team members."""
    add_territory(db)
    apns: set[str] = set()

    def add(apn: str, lon: float, lat: float, **kw):
        if apn in apns:
            return
        add_parcel(db, apn, lon, lat, **kw)
        apns.add(apn)

    for i, r in enumerate(pd.read_csv(STRO, dtype=str).itertuples()):
        if r.license_id != "STR-OUTSIDE":
            add(f"4000000{i:03d}", float(r.longitude), float(r.latitude), zoning="RS-1-4", lot=6000)

    for i, apn in enumerate(["3461201100", "3500701802", "3504004715"]):
        add(apn, -117.31 + i * 0.002, 32.86, zoning="RS-1-7", lot=7000)

    permits = pd.read_csv(PERMITS, dtype=str)
    permits = permits[permits.APPROVAL_TYPE != "Brand New Approval Type"]     # no label in permit_labels.yaml
    permit_path = tmp_path / "approvals_issued_filtered.csv"
    permits.to_csv(permit_path, index=False)

    for i, r in enumerate(permits.itertuples()):
        if i == 2:
            continue
        apn = clean_apn(r.GIS_APN)
        if apn:
            add(apn, float(r.GIS_LONGITUDE), float(r.GIS_LATITUDE), zoning="RS-1-4", lot=6500)
        elif i == 0:
            add("3999999990", float(r.GIS_LONGITUDE), float(r.GIS_LATITUDE), zoning="RS-1-4", lot=6500)
        elif i == 1:
            add("3999999991", -117.20, 32.80, situs=r.GIS_ADDRESS, zoning="RS-1-4", lot=6500)

    db.execute("update parcels set land_use='11' where land_use is null")

    for i, apn in enumerate(sorted(apns)):
        db.execute(
            "insert into owners (apn, owner_name, mailing_address, owner_occupied, absentee, out_of_state, "
            "last_sale_date, mortgage_open, est_value, est_equity, provider, is_sample, as_of) "
            "values (%s,%s,%s,true,false,false,'2001-01-01',false,%s,%s,'sample',true,%s)",
            (apn, f"Sample Owner {i:04d}",
             "homeowner@example.com 619-555-0100" if i == 0 else f"{1000 + i} Test Lane",
             1_200_000 + i * 10_000, 600_000 + i * 5_000, RUN_DATE))

    files = {
        "stro_licenses": STRO,
        "dev_permits": [permit_path],
        "code_enforcement": FIXTURES / "code_enforcement_empty.csv",
        "permit_signal_map": PERMIT_MAP,
        "tax_default": TAX,
        **_transit_files(tmp_path),
    }
    return files


def _lead_handler(task, system, messages):
    pk = json.loads(messages[0]["content"])
    recs = pk["records"]
    signal = next((r for r in recs if r["kind"] == "signal"), recs[-1])
    parcel = next((r for r in recs if r["kind"] == "parcel"), recs[0])
    return {"headline": "A long-held home with new activity",
            "suggested_angle": "Ask what the activity means for the owner's plans.",
            "summary": "The records show activity on this home. The property details are listed here.",
            "claims": [{"text": signal["text"], "record_ids": [signal["id"]]},
                       {"text": parcel["text"], "record_ids": [parcel["id"]]}]}


def _weekly_handler(task, system, messages):
    facts = json.loads(messages[0]["content"])
    hoods = list(facts.get("neighborhoods") or {"La Jolla": {}})
    return {"title": "A steady week",
            "intro": "Activity continued across the territory this week.",
            "sections": [{"neighborhood": h, "bullets": [f"Activity was recorded in {h}."]} for h in hoods],
            "newsletter_paragraph": NEWS}


def _fake():
    return FakeProvider(lambda task, system, messages: _lead_handler(task, system, messages)
                        if task == "lead_brief" else _weekly_handler(task, system, messages))


# ---------------------------------------------------------------------------------------
# cloud guard and CLI
# ---------------------------------------------------------------------------------------
def test_weekly_run_refuses_a_remote_host_without_cloud(monkeypatch):
    cloud = "postgresql://postgres:x@db.example.supabase.co:5432/postgres?sslmode=require"
    env = {**os.environ, "SUPABASE_DB_URL": cloud}
    r = subprocess.run([sys.executable, "-m", "territory.weekly_run", "--client", "kaiser-team", "--skip-ai"],
                       cwd=PIPELINES, env=env, capture_output=True, text=True, timeout=90)
    assert r.returncode != 0
    out = r.stderr + r.stdout
    assert "db.example.supabase.co" in out and "--cloud" in out


def test_cloud_flag_is_accepted_and_disables_the_local_cache(monkeypatch):
    seen: dict = {}

    def fake_run(client, **kw):
        seen.update(kw)
        return weekly_run.WeeklyResult()

    db.allow_cloud(False)
    monkeypatch.setattr(weekly_run, "run_weekly", fake_run)
    try:
        assert weekly_run.main(["--client", "kaiser-team", "--skip-ai", "--cloud"]) == 0
        assert db._CLOUD_OK is True
        assert seen["skip_ai"] is True and seen["use_cached_ingest"] is False
    finally:
        db.allow_cloud(False)


# ---------------------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------------------
def test_local_dry_run_skip_ai_runs_every_stage_and_writes_the_digest(db, tmp_path):
    files = _seed_weekly(db, tmp_path)
    out = __import__("io").StringIO()
    result = weekly_run.run_weekly(client(), run_date=RUN_DATE, skip_ai=True, local_files=files,
                                   report_dir=tmp_path, outbox_dir=tmp_path / "outbox", out=out)
    statuses = {s.name: s.status for s in result.stages}
    assert result.ok, out.getvalue()
    for name in ("stro_licenses", "dev_permits", "code_enforcement", "tax_default", "upzoning_estimate",
                 "permit_rederive", "portfolio", "score", "refresh_aggregates", "digest"):
        assert statuses[name] == "success", (name, statuses, out.getvalue())
    assert statuses["fire_zones"] == "awaiting"
    assert statuses["ai"] == "skipped"
    assert result.digest_path == tmp_path / "outbox" / "latest_digest.html"
    html = result.digest_path.read_text(encoding="utf-8")
    assert "Monday executive digest" in html and "Source health" in html
    assert "awaiting manual download" in html
    assert "Sample data" in html and "Estimated" in html
    assert "homeowner@example.com" not in html and "619-555-0100" not in html
    assert "Sample Owner" not in html
    assert db.execute("select count(*) from scores").fetchone()[0] > 0


def test_local_dry_run_with_fake_provider_runs_ai_and_keeps_spend_local(db, tmp_path):
    files = _seed_weekly(db, tmp_path)
    result = weekly_run.run_weekly(client(), run_date=RUN_DATE, skip_ai=False, provider=_fake(),
                                   local_files=files, report_dir=tmp_path, outbox_dir=tmp_path / "outbox",
                                   out=__import__("io").StringIO())
    statuses = {s.name: s.status for s in result.stages}
    assert result.ok and statuses["ai"] == "success"
    assert db.execute("select count(*) from latest_ai_outputs where task='weekly_brief'").fetchone()[0] == 1
    assert db.execute("select count(*) from latest_ai_outputs where task='lead_brief'").fetchone()[0] > 0
    html = result.digest_path.read_text(encoding="utf-8")
    assert "A steady week" in html and NEWS in html


def test_fire_zones_awaiting_manual_download_does_not_abort_the_batch(db, tmp_path):
    files = _seed_weekly(db, tmp_path)
    result = weekly_run.run_weekly(client(), run_date=RUN_DATE, skip_ai=True, local_files=files,
                                   report_dir=tmp_path, outbox_dir=tmp_path / "outbox",
                                   out=__import__("io").StringIO())
    fire = next(s for s in result.stages if s.name == "fire_zones")
    assert fire.status == "awaiting" and fire.detail == "awaiting manual download"
    assert next(s for s in result.stages if s.name == "score").status == "success"
    assert result.digest_path and result.digest_path.exists()


# ---------------------------------------------------------------------------------------
# digest rendering and privacy
# ---------------------------------------------------------------------------------------
APN = "3500000001"


def _seed_digest(db):
    add_territory(db)
    add_parcel(db, APN, -117.25, 32.85, situs="123 Main St", zoning="RS-1-4", lot=7000)
    db.execute("update parcels set land_use='11' where apn=%s", (APN,))
    db.execute(
        "insert into owners (apn, owner_name, mailing_address, owner_occupied, absentee, out_of_state, "
        "last_sale_date, mortgage_open, est_value, est_equity, provider, is_sample, as_of) "
        "values (%s,'Jane Homeowner','jane@example.com 619-555-0100',true,false,false,'2001-01-01',false,"
        "1500000,800000,'sample',true,%s)", (APN, RUN_DATE))
    db.execute(
        "insert into scores (apn, score, components, reason_text, recipe_matches, model_version, scored_at, "
        "uses_sample_data, primary_recipe) values (%s,82,'[]','Recent prep work by a long-time owner.',"
        "array['pre_list_prep'],'v0.5-handset','2026-11-18T00:00:00Z',true,'pre_list_prep')", (APN,))
    db.execute(
        "insert into ai_outputs (client_id, task, subject_type, subject_id, input_hash, prompt_version, provider, "
        "model, output, cited_record_ids, uses_sample, status) values "
        "('kaiser-team','weekly_brief','territory','2026-11-11','h','v1','fake','fake-model',%s,'{}',true,'valid')",
        (Jsonb({"title": "A steady week", "intro": "Activity continued across the territory this week.",
                "sections": [{"neighborhood": "La Jolla", "bullets": ["One new signal."]}],
                "newsletter_paragraph": NEWS}),))
    db.execute(
        "insert into ai_outputs (client_id, task, subject_type, subject_id, input_hash, prompt_version, provider, "
        "model, output, cited_record_ids, uses_sample, status) values "
        "('kaiser-team','lead_brief','parcel',%s,'h2','v1','fake','fake-model',%s,'{}',true,'valid')",
        (APN, Jsonb({"headline": "Long-held home with fresh prep work"})))


def test_digest_is_only_sent_when_the_flag_is_passed(db, tmp_path, monkeypatch):
    _seed_digest(db)
    calls: list[int] = []
    monkeypatch.setattr(digest, "send_digest", lambda *a, **kw: (calls.append(1) or ["agent@team.test"]))
    stage, path, sent = weekly_run._digest_stage(client(), date(2026, 11, 20), False, tmp_path)
    assert stage.status == "success" and path and path.exists() and calls == [] and sent == []
    stage, path, sent = weekly_run._digest_stage(client(), date(2026, 11, 20), True, tmp_path)
    assert stage.status == "success" and calls == [1] and sent == ["agent@team.test"]


def test_digest_renders_brief_leads_gci_and_disclosures(db):
    _seed_digest(db)
    data = digest.collect_digest_data(db, client(), today=date(2026, 11, 20))
    html_body, text_body = digest.render_digest(data)
    assert data["leads"][0]["address"] == "123 Main St"
    assert data["leads"][0]["score"] == 82
    assert data["leads"][0]["recipe"] == "Pre-list prep"
    assert data["leads"][0]["headline"] == "Long-held home with fresh prep work"
    assert data["leads"][0]["gci"] == 37_500
    assert f"https://kaiser-team-signals.mike-1d7.workers.dev/leads/{APN}" in html_body
    assert f"https://kaiser-team-signals.mike-1d7.workers.dev/leads/{APN}" in text_body
    assert "A steady week" in html_body and NEWS in html_body and NEWS in text_body
    assert "Sample data" in html_body and "Estimated" in html_body
    assert "Sample data" in text_body and "Estimated" in text_body
    assert "Est. $38k GCI" in html_body


def test_digest_never_contains_homeowner_contact_details(db):
    _seed_digest(db)
    data = digest.collect_digest_data(db, client(), today=date(2026, 11, 20))
    html_body, text_body = digest.render_digest(data)
    for forbidden in ("Jane Homeowner", "jane@example.com", "619-555-0100", "mailing_address"):
        assert forbidden not in html_body and forbidden not in text_body


def test_digest_escapes_untrusted_values(db):
    _seed_digest(db)
    db.execute("update parcels set situs_address='<script>alert(1)</script>' where apn=%s", (APN,))
    data = digest.collect_digest_data(db, client(), today=date(2026, 11, 20))
    html_body, _ = digest.render_digest(data)
    assert "<script>alert(1)</script>" not in html_body
    assert "&lt;script&gt;" in html_body


def test_digest_refuses_to_send_when_team_members_is_empty(db):
    db.execute("delete from team_members")
    env = {"SMTP_HOST": "smtp.test", "SMTP_PORT": "587", "DIGEST_FROM": "digest@team.test",
           "DIGEST_TO": "agent@team.test"}
    with pytest.raises(RuntimeError, match="team_members is empty"):
        digest.send_digest("<p>x</p>", "x", "s", conn=db, client=client(), env=env)


def test_digest_recipients_must_be_internal_team_members(db):
    db.execute("delete from team_members")
    db.execute("insert into team_members (email, name, role) values ('agent@team.test','Agent','agent')")
    env = {"SMTP_HOST": "smtp.test", "SMTP_PORT": "587", "SMTP_USER": "u", "SMTP_PASS": "p",
           "DIGEST_FROM": "digest@team.test", "DIGEST_TO": "homeowner@example.com"}
    with pytest.raises(RuntimeError, match="outside the internal team"):
        digest.send_digest("<p>x</p>", "x", "s", conn=db, client=client(), env=env)

    class FakeSMTP:
        def __init__(self, *a, **kw):
            self.sent = None
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def ehlo(self):
            pass
        def starttls(self):
            pass
        def login(self, *a):
            pass
        def send_message(self, msg):
            self.sent = msg

    env["DIGEST_TO"] = "agent@team.test"
    sent = digest.send_digest("<p>x</p>", "x", "s", conn=db, client=client(), env=env,
                              smtp_factory=lambda *a, **kw: FakeSMTP())
    assert sent == ["agent@team.test"]


# ---------------------------------------------------------------------------------------
# systemd / install kit
# ---------------------------------------------------------------------------------------
def _parse_unit(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections[current] = {}
        elif "=" in line and current:
            key, value = line.split("=", 1)
            sections[current][key.strip()] = value.strip()
    return sections


def test_systemd_units_have_the_weekly_monday_schedule_and_command():
    service = _parse_unit(SERVICE)
    timer = _parse_unit(TIMER)
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["EnvironmentFile"] == "/etc/territory-signals/kaiser-team.env"
    assert "python -m territory.weekly_run --client kaiser-team --cloud --send-digest" \
        in service["Service"]["ExecStart"]
    assert service["Service"]["WorkingDirectory"].endswith("/pipelines")
    assert timer["Timer"]["OnCalendar"] == "Mon *-*-* 05:30:00 America/Los_Angeles"
    assert timer["Timer"]["Persistent"] == "true"
    assert timer["Timer"]["Unit"] == "territory-weekly.service"
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_vps_install_script_is_idempotent_and_protects_the_env_file():
    text = INSTALL.read_text(encoding="utf-8")
    assert INSTALL.stat().st_mode & 0o111
    assert "requirements.txt" in text and ".venv" in text
    assert "/etc/territory-signals/kaiser-team.env" in text
    assert "chmod 600" in text
    assert "[[ ! -f \"$ENV_FILE\" ]]" in text            # never overwrites an existing env file
    assert "systemctl daemon-reload" in text and "systemctl enable territory-weekly.timer" in text
    assert "territory-weekly.service" in text and "territory-weekly.timer" in text
