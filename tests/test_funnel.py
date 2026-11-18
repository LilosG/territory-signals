"""stage_events (append-only) and the funnel views."""
import psycopg
import pytest
from psycopg.types.json import Jsonb

from helpers import add_territory
from test_scoring_db import parcel


def score_row(db, apn, score, recipes, scored_at="2026-11-18 10:00+00"):
    db.execute("insert into scores (apn, score, components, reason_text, recipe_matches, model_version, scored_at) "
               "values (%s,%s,%s,'x',%s,'v0.3-handset',%s)", (apn, score, Jsonb([]), recipes, scored_at))


def event(db, apn, stage, email=None, source="dashboard"):
    db.execute("insert into stage_events (apn, stage, team_member_email, source) values (%s,%s,%s,%s)",
               (apn, stage, email, source))


def seed(db):
    add_territory(db)
    for i in range(1, 5):
        parcel(db, f"500000000{i}", n=i)
    score_row(db, "5000000001", 70, ["str_exit", "tired_landlord"])
    score_row(db, "5000000002", 50, ["str_exit"])
    score_row(db, "5000000003", 90, ["builder_bait"])
    score_row(db, "5000000004", 10, [])                                  # no recipe: not in funnel_by_recipe


def test_stage_events_table_rules(db):
    seed(db)
    event(db, "5000000001", "signal", source="system")
    ev = db.execute("select id, apn, stage, team_member_email, occurred_at, note, source from stage_events").fetchone()
    assert ev[2] == "signal" and ev[4] is not None and ev[6] == "system"
    for stage in ("signal", "contacted", "conversation", "appointment", "listing", "not_interested", "bad_data"):
        event(db, "5000000001", stage)
    with pytest.raises(psycopg.errors.CheckViolation):
        event(db, "5000000001", "closed")
    with pytest.raises(psycopg.errors.CheckViolation):
        event(db, "5000000001", "contacted", source="phone")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        event(db, "no-such-apn", "contacted")


def test_stage_events_are_append_only(db):
    seed(db)
    event(db, "5000000001", "contacted", "a@example.test")
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update stage_events set stage = 'listing'")
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("delete from stage_events")


def test_rls_and_security_invoker(db):
    row = db.execute("select relrowsecurity from pg_class where relname = 'stage_events'").fetchone()
    assert row[0] is True
    pol = db.execute("select cmd, roles::text from pg_policies where tablename = 'stage_events'").fetchall()
    assert pol == [("SELECT", "{authenticated}")]                          # like the other tables: no write policies
    for view in ("funnel_by_recipe", "funnel_by_agent"):
        opts = db.execute("select reloptions from pg_class where relname = %s", (view,)).fetchone()[0]
        assert "security_invoker=true" in opts


def test_funnel_by_recipe_counts_distinct_parcels_per_stage(db):
    seed(db)
    event(db, "5000000001", "signal", source="system")
    event(db, "5000000002", "signal", source="system")
    event(db, "5000000003", "signal", source="system")
    event(db, "5000000001", "contacted", "a@example.test")
    event(db, "5000000001", "contacted", "a@example.test")              # duplicate event: still one parcel
    event(db, "5000000001", "conversation", "a@example.test")
    event(db, "5000000002", "not_interested", "b@example.test")
    event(db, "5000000003", "appointment", "b@example.test")
    event(db, "5000000004", "signal", source="system")
    cols = ["signal", "contacted", "conversation", "appointment", "listing", "not_interested", "bad_data"]
    got = {r[0]: dict(zip(cols, r[1:])) for r in db.execute(
        "select recipe, signal, contacted, conversation, appointment, listing, not_interested, bad_data "
        "from funnel_by_recipe")}
    assert set(got) == {"str_exit", "tired_landlord", "builder_bait"}
    assert got["str_exit"] == {"signal": 2, "contacted": 1, "conversation": 1, "appointment": 0, "listing": 0,
                               "not_interested": 1, "bad_data": 0}
    assert got["tired_landlord"]["contacted"] == 1 and got["tired_landlord"]["signal"] == 1
    assert got["builder_bait"]["appointment"] == 1


def test_funnel_by_agent(db):
    seed(db)
    event(db, "5000000001", "contacted", "a@example.test")
    event(db, "5000000002", "contacted", "a@example.test")
    event(db, "5000000003", "listing", "b@example.test")
    event(db, "5000000003", "signal", None, "system")
    got = {r[0]: r[1:] for r in db.execute(
        "select team_member_email, signal, contacted, listing, avg_score from funnel_by_agent")}
    assert got["a@example.test"] == (0, 2, 0, 60.0)                        # avg of scores 70 and 50
    assert got["b@example.test"][2] == 1 and got["b@example.test"][3] == 90.0
    assert got["unassigned"][0] == 1                                       # system events have no agent


def test_funnel_uses_only_the_latest_score(db):
    seed(db)
    score_row(db, "5000000001", 20, ["downsizer"], scored_at="2026-11-19 10:00+00")     # newer run: new recipe only
    event(db, "5000000001", "contacted", "a@example.test")
    recipes = {r[0] for r in db.execute("select recipe from funnel_by_recipe where contacted > 0")}
    assert recipes == {"downsizer"}
