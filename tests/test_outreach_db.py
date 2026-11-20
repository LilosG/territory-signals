"""Outreach generator end to end on the test database: selection, templates, rows, source_facts, rules."""
import ast
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from helpers import add_territory
from test_scoring_db import AS_OF, CFG, add_signal, parcel
from territory.config import ClientConfig, load_client
from territory.outreach import (
    main, mailing_for, pick_agents, primary_recipe, recipe_contribution, run_outreach, same_address,
)
from territory.score import run_score

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
SUP = Path(__file__).resolve().parents[1] / "pipelines" / "territory"


def client(team=(), recipes=None, **outreach):
    data = load_client("kaiser-team").model_dump()
    data["team_members"] = list(team)
    data["outreach"].update(outreach)
    for k, v in (recipes or {}).items():
        data["recipes"][k] = {"enabled": v}
    return ClientConfig.model_validate(data)


def agent(n, dre="01234567"):
    return {"name": f"Agent {n}", "email": f"agent{n}@example.test", "role": "agent", "dre_license": dre,
            "phone": f"(619) 555-010{n}"}


def add_owner(db, apn, name="SMITH JOHN & MARY", mailing=None, sale=date(1990, 1, 1), sample=False, absentee=False):
    db.execute("insert into owners (apn, owner_name, mailing_address, owner_occupied, absentee, out_of_state, "
               "last_sale_date, mortgage_open, provider, is_sample, as_of) values "
               "(%s,%s,%s,%s,%s,false,%s,true,'sample',%s,%s)",
               (apn, name, mailing, not absentee, absentee, sale, sample, AS_OF))


def seed(db, owners=None):
    """P1 str_exit, P2 financial_pressure, P3 builder_bait, P4 no recipe, P5 suppressed, P6 in cooldown.
    `owners` maps an apn to add_owner() overrides (owners rows are append-only, so they are set up front)."""
    add_territory(db)
    for i in range(1, 11):
        parcel(db, f"40000000{i:02d}", n=i)
        db.execute("update parcels set lot_sqft=%s, situs_address=%s, zip='92037' where apn=%s",
                   (10000 if i == 3 else 5000, f"{100 + i} PROSPECT ST", f"40000000{i:02d}"))
        add_owner(db, f"40000000{i:02d}", **(owners or {}).get(f"40000000{i:02d}", {}))
    ids = {}
    ids["p1"] = add_signal(db, "4000000001", "stro_license_removed", "stro", on=AS_OF)
    ids["p2"] = add_signal(db, "4000000002", "tax_default", "distress", on=AS_OF,
                           details={"tax_defaulted_on": "2021-06-30", "list": "June 2026"})
    ids["p3"] = db.execute(
        "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, run_id, "
        "confidence, match_method, is_estimate, details) values ('4000000003','sb9_lot_split_estimate','upzoning',"
        "%s,'test','4000000003-sb9',%s,0.9,'apn',true,'{\"zoning\": \"RS-1-7\"}') returning id",
        (AS_OF, db.execute("insert into source_runs (source_key, status) values ('test','success') returning id"
                           ).fetchone()[0])).fetchone()[0]
    add_signal(db, "4000000004", "permit_approved", "other", on=AS_OF, details={"approval_type": "Electrical Permit", "approval_id": "E1"})            # weight 0: no component, no recipe
    ids["p5"] = add_signal(db, "4000000005", "stro_license_removed", "stro", on=AS_OF)
    db.execute("insert into suppressions (apn, reason) values ('4000000005', 'asked not to be contacted')")
    add_signal(db, "4000000006", "stro_license_removed", "stro", on=AS_OF)
    db.execute("insert into outreach (apn, channel, status, content, created_at) "
               "values ('4000000006','mail','draft','old', %s)", (NOW - timedelta(days=10),))
    run_score(db, CFG, AS_OF)
    return ids


def rows(db):
    cur = db.execute("select apn, channel, status, content, source_facts, recipe, assigned_to, mailing_address, "
                     "salutation, template_key, model_version, blocked_reason, uses_sample_data from outreach "
                     "where content <> 'old' order by apn, channel")
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def test_selection_recipes_statuses_and_templates(db):
    seed(db)
    res = run_outreach(db, client(), CFG, now=NOW)
    got = {r["apn"]: r for r in rows(db)}
    # P4 has no recipe, P5 is suppressed, P6 is inside the 90-day cooldown
    assert set(got) == {"4000000001", "4000000002", "4000000003"}
    assert res["parcels"] == 3 and res["written"] == 3
    assert got["4000000001"]["recipe"] == "str_exit" and got["4000000001"]["template_key"] == "str_exit/letter"
    assert got["4000000003"]["recipe"] == "builder_bait" and got["4000000003"]["template_key"] == "builder_bait/letter"
    assert got["4000000002"]["recipe"] == "financial_pressure"
    # approval-required recipes go to awaiting_approval, the rest are drafts
    assert got["4000000002"]["status"] == "awaiting_approval"
    assert got["4000000001"]["status"] == got["4000000003"]["status"] == "draft"
    assert all(r["channel"] == "mail" and r["model_version"] == CFG["model_version"] for r in got.values())
    assert all(r["recipe"] in client().enabled_recipes() for r in got.values())


def test_top_drafts_per_run_by_score(db):
    seed(db)
    top = [r[0] for r in db.execute(
        "select apn from latest_scores where recipe_matches <> '{}' and apn in ('4000000001','4000000002','4000000003') "
        "order by score desc, apn")]
    run_outreach(db, client(drafts_per_run=2), CFG, now=NOW)
    assert [r["apn"] for r in rows(db)] == sorted(top[:2])


def test_disabled_recipes_are_not_drafted(db):
    seed(db)
    # P1 also matches financial_pressure (lost rental income + open mortgage), so turn that off too
    run_outreach(db, client(recipes={"str_exit": False, "financial_pressure": False}), CFG, now=NOW)
    assert {r["apn"] for r in rows(db)} == {"4000000003"}
    db.execute("delete from outreach")
    run_outreach(db, client(recipes={"str_exit": False}), CFG, now=NOW)       # next-best enabled recipe is used
    assert {r["apn"]: r["recipe"] for r in rows(db)}["4000000001"] == "financial_pressure"


def test_cooldown_blocks_a_second_run_and_dry_run_writes_nothing(db):
    seed(db)
    dry = run_outreach(db, client(), CFG, now=NOW, dry_run=True)
    assert len(dry["drafts"]) == 3 and dry["written"] == 0 and rows(db) == []
    run_outreach(db, client(), CFG, now=NOW)
    again = run_outreach(db, client(), CFG, now=NOW)
    assert again["parcels"] == 0 and len(rows(db)) == 3
    # Rows get the database's real created_at; pin them to the test clock so the test does not depend on today's date.
    db.execute("update outreach set created_at = %s where content <> 'old'", (NOW,))
    later = run_outreach(db, client(), CFG, now=NOW + timedelta(days=91))      # cooldown over
    assert later["parcels"] == 4                                               # P6's old row has aged out too


def test_suppressed_by_a_recent_sale_even_if_scored_earlier(db):
    seed(db)
    db.execute("insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) "
               "values ('4000000001','2026-06-01',900000,'grant deed','sample',true)")
    run_outreach(db, client(), CFG, now=NOW)
    assert "4000000001" not in {r["apn"] for r in rows(db)}


def test_only_the_latest_scoring_run_is_used(db):
    seed(db)
    # an older run scored 4000000007 with a recipe; the newest run did not score it at all
    add_signal(db, "4000000007", "stro_license_removed", "stro", on=AS_OF)
    run_score(db, CFG, AS_OF, scored_at=NOW - timedelta(days=30))
    run_score(db, CFG, AS_OF)
    db.execute("insert into suppressions (apn, reason) values ('4000000007', 'x')")
    run_score(db, CFG, AS_OF)                                                  # 4000000007 is now unscored
    run_outreach(db, client(), CFG, now=NOW)
    assert "4000000007" not in {r["apn"] for r in rows(db)}


def test_blocked_reasons_and_round_robin_assignment(db):
    seed(db)
    run_outreach(db, client(), CFG, now=NOW)                                   # no team members configured
    assert {r["blocked_reason"] for r in rows(db)} == {"missing agent name or DRE license"}
    assert {r["assigned_to"] for r in rows(db)} == {None}
    db.execute("delete from outreach")
    c = client(team=[agent(2), agent(1, dre="")])                              # agent 1 has no DRE license
    run_outreach(db, c, CFG, now=NOW)
    got = rows(db)
    ranked = [r[0] for r in db.execute(                                        # draft order = score order
        "select o.assigned_to from outreach o join latest_scores s on s.apn = o.apn "
        "where o.content <> 'old' order by s.score desc, s.apn")]
    # (deleting all outreach rows also cleared P6's cooldown row, so four parcels are drafted)
    assert ranked == ["agent1@example.test", "agent2@example.test", "agent1@example.test", "agent2@example.test"]
    for r in got:
        expected = "missing agent name or DRE license" if r["assigned_to"] == "agent1@example.test" else None
        assert r["blocked_reason"] == expected
    ok = next(r for r in got if r["assigned_to"] == "agent2@example.test")
    assert "Agent 2 · The Kaiser Team · DRE #01234567" in ok["content"]
    # only agents are assigned (not owners/assistants)
    assert [m.email for m in pick_agents(client(team=[agent(1), {**agent(2), "role": "assistant"}]))] == ["agent1@example.test"]


def test_round_robin_continues_across_runs(db):
    seed(db)
    c = client(team=[agent(1), agent(2)], drafts_per_run=1)
    run_outreach(db, c, CFG, now=NOW)
    run_outreach(db, c, CFG, now=NOW)
    assert [r[0] for r in db.execute(
        "select assigned_to from outreach where content <> 'old' order by created_at")] == [
        "agent1@example.test", "agent2@example.test"]


def test_email_drafts_need_an_office_address(db):
    seed(db)
    data = client(team=[agent(1)]).model_dump()
    data["team_profile"]["office_address"] = ""
    run_outreach(db, ClientConfig.model_validate(data), CFG, channels=("mail", "email", "call_task"), now=NOW)
    by = {}
    for r in rows(db):
        by.setdefault(r["channel"], set()).add(r["blocked_reason"])
    assert by == {"mail": {None}, "email": {"missing office address"}, "call_task": {None}}
    data["team_profile"]["office_address"] = "1 Test Way, San Diego, CA 92037"
    db.execute("delete from outreach")
    run_outreach(db, ClientConfig.model_validate(data), CFG, channels=("email",), now=NOW)
    assert {r["blocked_reason"] for r in rows(db)} == {None}


def test_all_three_channels_use_their_own_templates(db):
    seed(db)
    run_outreach(db, client(team=[agent(1)]), CFG, channels=("mail", "email", "call_task"), drafts=1, now=NOW)
    got = rows(db)
    assert {r["channel"] for r in got} == {"mail", "email", "call_task"} and len(got) == 3
    assert {r["template_key"].split("/")[1] for r in got} == {"letter", "email", "call_script"}
    call = next(r for r in got if r["channel"] == "call_task")
    assert call["content"].rstrip().endswith("Manual dial only. Check Do Not Call status before calling.")
    assert next(r for r in got if r["channel"] == "email")["content"].lstrip().startswith("Subject: ")


def test_mailing_address_rule(db):
    seed(db, owners={"4000000001": {"mailing": "9 Elsewhere Ave, Austin, TX 78701"},          # different: mail there
                     "4000000003": {"mailing": "103 Prospect St, San Diego, CA 92037"}})     # same street as situs
    run_outreach(db, client(), CFG, now=NOW)
    got = {r["apn"]: r["mailing_address"] for r in rows(db)}
    assert got["4000000001"] == "9 Elsewhere Ave, Austin, TX 78701"
    assert got["4000000003"] == "103 Prospect St, San Diego, CA 92037"
    assert got["4000000002"] == "102 Prospect St, San Diego, CA 92037"                       # no mailing address: situs
    assert mailing_for(None, "1 MAIN ST", None) == "1 Main St, San Diego, CA"
    assert mailing_for("", None, None) is None
    assert same_address("103 PROSPECT ST", "103 Prospect St, San Diego, CA 92037")
    assert not same_address("9 Elsewhere Ave", "103 Prospect St")


def test_salutation_comes_from_the_owner_name_with_address_fallback(db):
    seed(db, owners={"4000000002": {"name": "ABC HOLDINGS LLC"},
                     "4000000003": {"name": "Sample Owner 0003", "sample": True}})
    run_outreach(db, client(), CFG, now=NOW)
    got = {r["apn"]: r for r in rows(db)}
    assert got["4000000001"]["salutation"] == "Dear John and Mary Smith,"
    assert got["4000000001"]["content"].startswith("Dear John and Mary Smith,\n\n")
    assert got["4000000002"]["salutation"] == "To the owners of 102 Prospect St,"
    assert got["4000000003"]["salutation"] == "To the owners of 103 Prospect St,"


def test_source_facts_list_exactly_what_the_text_uses(db):
    ids = seed(db)
    run_outreach(db, client(), CFG, now=NOW)
    got = {r["apn"]: r for r in rows(db)}
    for r in got.values():
        for f in r["source_facts"]:
            assert f.get("signal_id") or f.get("owner_field") or f.get("parcel_field")   # each fact is traceable
    # builder bait: the zoning estimate (and the owner name used in the greeting), nothing else
    bb = got["4000000003"]["source_facts"]
    comp = [f for f in bb if f["kind"] == "component"]
    assert [(f["key"], f["signal_id"], f["is_estimate"]) for f in comp] == [
        ("sb9_lot_split_estimate", str(ids["p3"]), True)]
    assert comp[0]["source_key"] == "test" and comp[0]["match_method"] == "apn" and comp[0]["confidence"] == 0.9
    assert "estimated" not in got["4000000003"]["content"] and "SB 9" not in got["4000000003"]["content"]
    assert {(f["parcel_field"], f["value"]) for f in bb if f["kind"] == "parcel_field"} == {
        ("neighborhood", "La Jolla"), ("situs_address", "103 PROSPECT ST")}      # neighborhood and street are used
    # str_exit: the removed-license component, never the tax default or owner details
    assert [f["key"] for f in got["4000000001"]["source_facts"] if f["kind"] == "component"] == ["stro_license_removed"]
    # financial_pressure never mentions (or cites) the tax default
    fp = got["4000000002"]
    assert [f for f in fp["source_facts"] if f["kind"] == "component"] == []
    assert {f["parcel_field"] for f in fp["source_facts"] if f["kind"] == "parcel_field"} == {"neighborhood", "situs_address"}
    assert "tax" not in fp["content"].lower() and "default" not in fp["content"].lower()
    owner_facts = [f for f in got["4000000001"]["source_facts"] if f["kind"] == "owner_field"]
    assert [(f["owner_field"], f["value"]) for f in owner_facts] == [("owner_name", "SMITH JOHN & MARY")]
    # a call script does not use the owner's name, so it cites no owner field
    db.execute("delete from outreach")
    run_outreach(db, client(), CFG, channels=("call_task",), now=NOW)
    assert all(f["kind"] != "owner_field" for r in rows(db) for f in r["source_facts"])


def test_sample_data_drafts_are_blocked_with_a_reason_not_a_banner(db):
    seed(db, owners={"4000000003": {"name": "Sample Owner 0003", "sample": True}})
    run_outreach(db, client(team=[agent(1)]), CFG, now=NOW)                    # a complete agent: only sample blocks
    got = {r["apn"]: r for r in rows(db)}
    s = got["4000000003"]
    assert s["uses_sample_data"] is True and s["blocked_reason"] == "sample data"
    assert "SAMPLE" not in s["content"].upper() and not s["content"].startswith("[")      # no label in the text
    assert got["4000000001"]["uses_sample_data"] is False and got["4000000001"]["blocked_reason"] is None
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("update outreach set status='approved' where apn='4000000003' and content <> 'old'")
    db.execute("delete from outreach")
    run_outreach(db, client(), CFG, now=NOW)                                   # reasons are combined
    assert {r["apn"]: r["blocked_reason"] for r in rows(db)}["4000000003"] == (
        "missing agent name or DRE license; sample data")


def test_a_blocked_draft_cannot_be_approved_or_sent(db):
    seed(db)
    run_outreach(db, client(), CFG, now=NOW)                                    # everything blocked (no agents)
    for status in ("approved", "sent"):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute("update outreach set status=%s where content <> 'old'", (status,))
    db.execute("delete from outreach")
    run_outreach(db, client(team=[agent(1)]), CFG, now=NOW)
    db.execute("update outreach set status='approved', approved_by='m@example.test' where content <> 'old'")
    assert {r["status"] for r in rows(db)} == {"approved"}


def test_recent_transfers_do_not_suppress_but_recent_sales_do(db):
    seed(db)
    db.execute("insert into sales_history (apn, sale_date, sale_price, doc_type, provider, is_sample) values "
               "('4000000001','2026-06-01',null,'Trust Transfer Deed','sample',true)")   # a transfer, case differs
    run_outreach(db, client(), CFG, now=NOW)
    assert "4000000001" in {r["apn"] for r in rows(db)}


def test_recipe_choice_uses_the_highest_contributing_recipe():
    comps = [{"kind": "signal", "signal_type": "tax_default", "group": "distress", "contribution": 28.0, "key": "tax_default"},
             {"kind": "signal", "signal_type": "stro_license_removed", "group": "stro", "contribution": 5.0, "key": "x"},
             {"kind": "owner", "owner_field": "absentee", "contribution": 10.0, "key": "owner:absentee"},
             {"kind": "owner", "owner_field": "last_sale_date", "contribution": 15.0, "key": "owner:years_owned"}]
    r = CFG["recipes"]
    assert recipe_contribution(r["financial_pressure"], comps) == 33.0         # tax default + removed license
    assert recipe_contribution(r["str_exit"], comps) == 5.0
    enabled = list(client().enabled_recipes())
    assert primary_recipe(["str_exit", "financial_pressure"], enabled, CFG, comps) == "financial_pressure"
    assert primary_recipe(["str_exit", "financial_pressure"], ["str_exit"], CFG, comps) == "str_exit"
    assert primary_recipe(["quiet_inheritance"], enabled, CFG, comps) is None
    # ties go to config order
    assert primary_recipe(["downsizer", "str_exit"], enabled, CFG, []) == "str_exit"


def test_cli_dry_run_prints_a_summary(db, capsys):
    seed(db)
    assert main(["--client", "kaiser-team", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN: 3 parcels, 3 drafts (0 written)") and rows(db) == []


def test_preview_mode_never_calls_external_services():
    banned = {"requests", "urllib", "urllib3", "http", "httpx", "smtplib", "socket", "ssl", "aiohttp", "ftplib",
              "anthropic", "openai", "subprocess", "territory.net"}
    for name in ("outreach.py", "outreach_render.py", "salutation.py", "export_catalog.py"):
        tree = ast.parse((SUP / name).read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for m in mods:
                assert m.split(".")[0] not in banned and m not in banned, f"{name} imports {m}"
    assert client().outreach.mode == "preview"


def test_scorer_stores_each_parcels_primary_recipe(db):
    seed(db)
    got = dict(db.execute("select apn, primary_recipe from latest_scores").fetchall())
    assert got["4000000003"] == "builder_bait" and got["4000000001"] == "str_exit"
    assert got["4000000004"] is None                                            # no recipe matched
    matches = {a: m for a, m in db.execute("select apn, recipe_matches from latest_scores")}
    assert all(p is None or p in matches[a] for a, p in got.items())


def test_the_generated_catalog_is_not_git_ignored():
    import subprocess
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run(["git", "check-ignore", "dashboard/src/data/catalog.generated.json"], cwd=root,
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stdout                                          # 1 = not ignored
