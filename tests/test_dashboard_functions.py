"""Phase 5B database functions: team gate, approve/edit, record_stage, share links, read functions.

Callers are simulated the way PostgREST does it: `set local role authenticated|anon` plus the JWT claims.
"""
import json
from contextlib import contextmanager

import psycopg
import pytest

from helpers import add_territory
from test_funnel import score_row
from test_scoring_db import add_signal, parcel

MEMBER = "agent@example.test"
STRANGER = "stranger@example.test"
APN = "6000000001"


@pytest.fixture
def d(db):
    add_territory(db)
    parcel(db, APN, n=1)
    db.execute("update parcels set situs_address='1 Secret St', zoning='RS-1-7', lot_sqft=6000, year_built=1955 where apn=%s", (APN,))
    score_row(db, APN, 70, ["downsizer"])
    # Supabase grants table access to anon/authenticated by default; a bare test database does not.
    db.execute("grant usage on schema public, extensions to anon, authenticated")
    db.execute("grant select on all tables in schema public to anon, authenticated")
    db.execute("delete from team_members")
    db.execute("insert into team_members (email, name, role) values (%s, 'Ada Agent', 'agent')", (MEMBER,))
    yield db
    db.execute("delete from team_members")


@contextmanager
def as_user(db, email, role="authenticated"):
    """Run statements as the given JWT user inside a transaction that is always rolled back."""
    db.execute("begin")
    try:
        db.execute(f"set local role {role}")
        db.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps({"email": email}),))
        yield db
    finally:
        db.execute("rollback")


def outreach(db, status="draft", blocked=None, apn=APN):
    return db.execute(
        "insert into outreach (apn, channel, status, content, blocked_reason) values (%s,'mail',%s,'Hello',%s) returning id",
        (apn, status, blocked)).fetchone()[0]


def test_non_team_user_is_rejected_by_every_action(d):
    oid = outreach(d)
    calls = [
        ("select approve_outreach(%s)", (oid,)),
        ("select edit_outreach(%s, 'x')", (oid,)),
        ("select record_stage(%s, 'contacted', null)", (APN,)),
        ("select create_share_link(%s)", (APN,)),
        ("select revoke_share_link('abc')", ()),
    ]
    for sql, args in calls:
        with as_user(d, STRANGER):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                d.execute(sql, args)


def test_anonymous_cannot_call_actions(d):
    oid = outreach(d)
    with as_user(d, MEMBER, role="anon"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            d.execute("select approve_outreach(%s)", (oid,))


def test_non_team_user_reads_no_rows(d):
    with as_user(d, STRANGER):
        assert d.execute("select count(*) from parcels").fetchone()[0] == 0
        assert d.execute("select count(*) from outreach").fetchone()[0] == 0
        assert d.execute("select count(*) from leads_page()").fetchone()[0] == 0
    with as_user(d, MEMBER):
        assert d.execute("select count(*) from parcels").fetchone()[0] == 1
        assert d.execute("select count(*) from leads_page()").fetchone()[0] == 1


def test_blocked_draft_cannot_be_approved(d):
    oid = outreach(d, blocked="missing agent name or DRE license")
    with as_user(d, MEMBER):
        with pytest.raises(psycopg.errors.CheckViolation, match="missing agent name"):
            d.execute("select approve_outreach(%s)", (oid,))
    assert d.execute("select status, approved_by from outreach where id=%s", (oid,)).fetchone() == ("draft", None)


def test_unblocked_draft_is_approved_by_caller_only_in_preview(d):
    oid = outreach(d)
    with as_user(d, MEMBER.upper()):  # email case does not matter
        d.execute("select approve_outreach(%s)", (oid,))
        assert d.execute("select status, approved_by, sent_at from outreach where id=%s", (oid,)).fetchone() == ("approved", MEMBER, None)


def test_cannot_approve_twice(d):
    oid = outreach(d, status="approved")
    with as_user(d, MEMBER):
        with pytest.raises(psycopg.errors.RaiseException, match="already approved"):
            d.execute("select approve_outreach(%s)", (oid,))


def test_edit_saves_text_original_and_editor(d):
    oid = outreach(d)
    with as_user(d, MEMBER):
        d.execute("select edit_outreach(%s, 'Edited once')", (oid,))
        d.execute("select edit_outreach(%s, 'Edited twice')", (oid,))
        row = d.execute("select content, original_content, edited_by, edited_at is not null from outreach where id=%s", (oid,)).fetchone()
    assert row == ("Edited twice", "Hello", MEMBER, True)
    with as_user(d, MEMBER):
        with pytest.raises(psycopg.errors.RaiseException):
            d.execute("select edit_outreach(%s, '   ')", (oid,))


def test_record_stage_inserts_events(d):
    with as_user(d, MEMBER):
        d.execute("select record_stage(%s, 'contacted', ' left a voicemail ')", (APN,))
        d.execute("select record_stage(%s, 'conversation', null)", (APN,))
        rows = d.execute("select stage, team_member_email, note, source from stage_events order by occurred_at, stage").fetchall()
        with pytest.raises(psycopg.errors.RaiseException):
            d.execute("select record_stage(%s, 'signal', null)", (APN,))
        d.execute("rollback")
        d.execute("begin")
        d.execute("set local role authenticated")
        d.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps({"email": MEMBER}),))
        with pytest.raises(psycopg.errors.CheckViolation):
            d.execute("select record_stage(%s, 'closed', null)", (APN,))
    got = {(r[0], r[1], r[2], r[3]) for r in rows}
    assert ("contacted", MEMBER, "left a voicemail", "dashboard") in got
    assert ("signal", MEMBER, None, "system") in got       # the funnel entry is written once
    assert sum(1 for r in rows if r[0] == "signal") == 1


def test_share_page_exposes_property_facts_only(d):
    d.execute("insert into owners (apn, owner_name, mailing_address, est_value, est_equity, mortgage_open, provider, is_sample, as_of, "
              "last_sale_date, last_sale_price) values (%s,'SECRET OWNER','9 Mailing Ln, Seattle, WA',5000000,3000000,true,'sample',true,'2026-11-18','2001-01-01',100)", (APN,))
    d.execute("insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) values (%s,'2001-01-01',777777,'grant deed','sample',true)", (APN,))
    add_signal(d, APN, "tax_default", group="distress")
    d.execute("insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, confidence, "
              "match_method, is_estimate) values (%s,'sb9_lot_split_estimate','upzoning','2026-11-18','test','sb9-1',0.9,'spatial',true)", (APN,))
    with as_user(d, MEMBER):
        tok = d.execute("select create_share_link(%s)", (APN,)).fetchone()[0]
        assert len(tok) >= 48
    # the link above was created in a rolled-back transaction; insert a committed one for the public read
    d.execute("insert into share_links (token, apn, created_by) values ('tok-public', %s, %s)", (APN, MEMBER))
    with as_user(d, "", role="anon"):
        cur = d.execute("select * from share_page('tok-public')")
        cols = [c.name for c in cur.description]
        row = cur.fetchone()
    assert cols == ["neighborhood", "lot_sqft", "zoning", "year_built", "upzoning_estimates", "agent_name", "agent_email"]
    assert row[0] == "La Jolla" and row[2] == "RS-1-7" and row[3] == 1955
    assert row[4] == ["sb9_lot_split_estimate"] and row[5] == "Ada Agent" and row[6] == MEMBER
    text = json.dumps(row, default=str)
    for secret in ("SECRET OWNER", "Mailing", "5000000", "3000000", "777777", "Secret St", "6000000001", "tax_default", "distress"):
        assert secret not in text
    with as_user(d, "", role="anon"):
        assert d.execute("select count(*) from share_page('nope')").fetchone()[0] == 0
        assert d.execute("select count(*) from share_links").fetchone()[0] == 0   # RLS: anon sees no rows


def test_revoked_share_link_shows_nothing(d):
    d.execute("insert into share_links (token, apn, created_by) values ('tok-r', %s, %s)", (APN, MEMBER))
    with as_user(d, "", role="anon"):
        assert d.execute("select count(*) from share_page('tok-r')").fetchone()[0] == 1
    with as_user(d, MEMBER):
        d.execute("select revoke_share_link('tok-r')")
        assert d.execute("select revoked_at is not null from share_links where token='tok-r'").fetchone()[0]
        with pytest.raises(psycopg.errors.RaiseException):
            d.execute("select revoke_share_link('tok-r')")
    with as_user(d, MEMBER):
        with pytest.raises(psycopg.errors.RaiseException):
            d.execute("select revoke_share_link('missing')")
    with as_user(d, STRANGER):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            d.execute("select revoke_share_link('tok-r')")


def test_auth_gate_trigger_blocks_non_team_emails(d):
    """The trigger is attached to auth.users on Supabase; here a stub table proves the gate function."""
    d.execute("create schema if not exists auth")
    d.execute("create table auth.users (id uuid primary key default gen_random_uuid(), email text)")
    try:
        d.execute("create trigger auth_gate_team_only before insert on auth.users "
                  "for each row execute function public.auth_gate_team_only()")
        d.execute("insert into auth.users (email) values (%s)", (MEMBER.upper(),))        # on the team (any case)
        with pytest.raises(psycopg.errors.RaiseException, match="not on the team"):
            d.execute("insert into auth.users (email) values (%s)", (STRANGER,))
        with pytest.raises(psycopg.errors.RaiseException, match="not on the team"):
            d.execute("insert into auth.users (email) values (null)")
    finally:
        d.execute("drop table auth.users")
        d.execute("drop schema auth")


def test_leads_page_filters_and_paginates(d):
    for i in range(2, 6):
        parcel(d, f"600000000{i}", n=i)
        score_row(d, f"600000000{i}", 40 + i, ["downsizer"] if i % 2 else [])
    with as_user(d, MEMBER):
        rows = d.execute("select apn, total from leads_page(p_limit=>2)").fetchall()
        assert len(rows) == 2 and rows[0][1] == 5 and rows[0][0] == APN          # highest score first, total before paging
        assert [r[0] for r in d.execute("select apn from leads_page(p_limit=>2, p_offset=>4)").fetchall()] == ["6000000002"]
        assert d.execute("select count(*) from leads_page(p_recipe=>'downsizer')").fetchone()[0] == 3
        assert d.execute("select count(*) from leads_page(p_min=>45)").fetchone()[0] == 2
        pts = d.execute("select map_points(p_recipe=>'downsizer')").fetchone()[0]
        assert len(pts) == 3 and set(map(type, pts[0])) <= {str, int, float, type(None)}


def test_today_stat_history_buckets_weeks_and_reports_the_first_data_day(d):
    """Phase 5G: weekly counts (0 = the last 7 days, 1 = the week before) and the day each metric first had data."""
    from datetime import timedelta
    today = d.execute("select current_date").fetchone()[0]                       # the database's date, not this machine's
    rid = d.execute("insert into source_runs (source_key, status, started_at) values ('dev_permits', 'success', %s) returning id",
                    (today - timedelta(days=9),)).fetchone()[0]
    d.execute("insert into source_runs (source_key, status, started_at) values ('tax_default', 'success', %s)", (today - timedelta(days=30),))
    for day, n in [(0, 2), (6, 1), (7, 4), (13, 1), (14, 5)]:                      # weeks 0, 0, 1, 1, 2
        for i in range(n):
            d.execute(
                "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, run_id, confidence, match_method) "
                "values (%s,'permit_approved','remodel_addition',%s,'dev_permits',%s,%s,0.9,'apn')",
                (APN, today - timedelta(days=day), f"H-{day}-{i}", rid))
    d.execute("insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, run_id, confidence, match_method) "
              "values (%s,'permit_approved','other',%s,'dev_permits','H-other',%s,0.9,'apn')", (APN, today, rid))   # 'other' never counts
    with as_user(d, MEMBER):
        rows = d.execute("select metric, weeks_ago, n, first_day from today_stat_history(null) order by metric, weeks_ago").fetchall()
        hood = d.execute("select weeks_ago, n from today_stat_history('Nowhere') where metric = 'signals' order by weeks_ago limit 3").fetchall()
    sig = [r for r in rows if r[0] == "signals"]
    assert [r[1] for r in sig] == list(range(13))
    assert [r[2] for r in sig][:4] == [3, 5, 5, 0]                                 # 2 + 1 | 4 + 1 | 5 | none
    assert {r[3] for r in sig} == {today - timedelta(days=9)}                      # first successful pull of dev_permits / stro, not tax_default
    assert {r[0] for r in rows} == {"signals", "drafts", "outcomes", "active_leads"}
    assert all(r[3] is None for r in rows if r[0] == "outcomes")                   # no outcome ever logged
    assert hood == [(0, 0), (1, 0), (2, 0)]                                        # filtered to a neighborhood with nothing
    with as_user(d, STRANGER):
        assert d.execute("select count(*) from today_stat_history(null) where n > 0").fetchone()[0] == 0   # RLS: a non-member sees no rows
    with as_user(d, MEMBER, role="anon"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            d.execute("select * from today_stat_history(null)")
