"""AI tasks on the test database with the fake provider: storage, cache, budget guard, skip-when-no-key, append-only."""
import io
import json
from datetime import date

import psycopg
import pytest
from psycopg.types.json import Jsonb

from helpers import add_territory
from test_scoring_db import AS_OF, CFG, add_signal, parcel, run_id
from territory.config import ClientConfig, load_client
from territory.llm import store
from territory.llm.fake import FakeProvider
from territory.llm.runner import run_ai
from territory.llm.tasks import lead_brief, permit_intent, weekly_brief
from territory.score import run_score


def client(**llm):
    data = load_client("kaiser-team").model_dump()
    data["llm"] = {**data["llm"], "model": "fake-model", "tasks": {}, **llm}
    return ClientConfig.model_validate(data)


def add_permit(db, apn, rid, text, on=AS_OF, group="pre_sale_prep"):
    db.execute(
        "insert into signals (apn, signal_type, signal_group, signal_date, source_key, source_record_id, run_id, "
        "confidence, match_method, details) values (%s,'permit_approved',%s,%s,'dev_permits',%s,%s,0.95,'apn',%s)",
        (apn, group, on, rid, run_id(db), Jsonb({"scope": text, "approval_type": "Electrical Permit"})))


def permit_handler(task, system, messages):
    items = json.loads(messages[0]["content"])
    return {"items": [{"id": it["id"], "intent": "maintenance", "scope_tags": ["hvac"], "confidence": 0.9,
                       "quote": " ".join(it["description"].split()[:3]), "reason": "Routine equipment replacement."}
                      for it in items]}


def seed_permits(db, n=4):
    add_territory(db)
    for i in range(n):
        parcel(db, f"500000000{i}", n=i)
        add_permit(db, f"500000000{i}", f"PMT-{i}", f"Replace furnace and ductwork at unit {i} of the house")


def stats_for(db, cl, provider, tasks, **kw):
    out = io.StringIO()
    return run_ai(db, cl, tasks=tasks, provider=provider, out=out, **kw)


def test_permit_intent_stores_valid_rows_with_cost_and_citation(db):
    seed_permits(db)
    f = FakeProvider(permit_handler)
    s = stats_for(db, client(), f, ["permit_intent"])[0]
    assert (s.calls, s.valid, s.invalid, s.rejected, s.cached) == (1, 4, 0, 0, 0)            # one batch call for 4 permits
    rows = db.execute("select subject_type, subject_id, status, cited_record_ids, prompt_version, provider, model, "
                      "output->>'intent', cost_usd from ai_outputs order by subject_id").fetchall()
    assert [r[1] for r in rows] == [f"PMT-{i}" for i in range(4)] and {r[2] for r in rows} == {"valid"}
    assert rows[0][0] == "permit" and rows[0][3] == ["PMT-0"] and rows[0][4] == "v1" and rows[0][5] == "fake" and rows[0][7] == "maintenance"
    assert sum(float(r[8]) for r in rows) == pytest.approx(0.001)                                # call cost split across rows
    run = db.execute("select task, status, calls, valid, cost_usd from ai_task_runs").fetchone()
    assert run[:4] == ("permit_intent", "success", 1, 4)


def test_cache_skips_the_call_when_input_and_prompt_version_match(db):
    seed_permits(db)
    f = FakeProvider(permit_handler)
    stats_for(db, client(), f, ["permit_intent"])
    s = stats_for(db, client(), f, ["permit_intent"])[0]
    assert len(f.calls) == 1 and s.calls == 0 and s.cached == 4
    # a changed description is a new input: only that permit is sent again
    add_permit(db, "5000000000", "PMT-NEW", "Install new boiler and radiators in the house")
    s = stats_for(db, client(), f, ["permit_intent"])[0]
    assert s.calls == 1 and s.cached == 4 and len(f.calls) == 2
    # a new prompt version invalidates the cache
    assert store.find_cached(db, "kaiser-team", "permit_intent", "PMT-0", store.input_hash(
        {"d": "Replace furnace and ductwork at unit 0 of the house", "t": "Electrical work"}), "v2") is None


def test_rejected_and_invalid_outputs_are_stored_but_never_shown(db):
    seed_permits(db, 3)

    def handler(task, system, messages):
        items = json.loads(messages[0]["content"])
        out = [{"id": it["id"], "intent": "maintenance", "scope_tags": [], "confidence": 0.9,
                "quote": "quote that is not in the text" if it["id"] == 2 else " ".join(it["description"].split()[:3]),
                "reason": "r"} for it in items if it["id"] != 3]                      # id 2 rejected (bad quote), id 3 missing
        return {"items": out}
    s = stats_for(db, client(), FakeProvider(handler), ["permit_intent"])[0]
    assert (s.valid, s.rejected, s.invalid) == (1, 1, 1)       # final outcome per permit, after the retry
    # the retry asked again for the two failed permits only; every attempt is stored
    assert db.execute("select status, attempt, count(*) from ai_outputs group by 1, 2 order by 1, 2").fetchall() == [
        ("invalid", 1, 1), ("invalid", 2, 1), ("rejected", 1, 1), ("rejected", 2, 1), ("valid", 1, 1)]
    assert db.execute("select count(*) from latest_ai_outputs").fetchone()[0] == 1          # only the valid row is readable
    assert db.execute("select rejection_reason from ai_outputs where status='rejected'").fetchone()[0].startswith("quoted words")


def test_a_wholly_invalid_reply_is_retried_once_then_stored_as_invalid(db):
    seed_permits(db, 2)
    f = FakeProvider(replies=["garbage", "still garbage"])
    s = stats_for(db, client(), f, ["permit_intent"])[0]
    assert len(f.calls) == 2 and s.invalid == 2 and s.valid == 0
    assert db.execute("select count(*) from ai_outputs where status='invalid' and output is null").fetchone()[0] == 4   # 2 permits x 2 attempts
    assert db.execute("select count(*) from latest_ai_outputs").fetchone()[0] == 0


def test_ai_outputs_are_append_only(db):
    seed_permits(db, 1)
    stats_for(db, client(), FakeProvider(permit_handler), ["permit_intent"])
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("update ai_outputs set status = 'valid'")
    with pytest.raises(psycopg.errors.RestrictViolation):
        db.execute("delete from ai_outputs")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into ai_outputs (client_id, task, subject_type, subject_id, input_hash, prompt_version, provider, model, status) "
                   "values ('c','t','house','1','h','v1','p','m','valid')")


def test_latest_ai_outputs_returns_the_newest_valid_row(db):
    seed_permits(db, 1)
    ins = ("insert into ai_outputs (client_id, task, subject_type, subject_id, input_hash, prompt_version, provider, model, status, output, created_at) "
           "values ('c','lead_brief','parcel','1',%s,'v1','p','m',%s,%s,%s)")
    db.execute(ins, ("a", "valid", Jsonb({"v": 1}), "2026-11-01"))
    db.execute(ins, ("b", "valid", Jsonb({"v": 2}), "2026-11-02"))
    db.execute(ins, ("c", "rejected", None, "2026-11-03"))
    assert db.execute("select output->>'v' from latest_ai_outputs where subject_id='1'").fetchall() == [("2",)]


# ---- budget guard ---------------------------------------------------------------------------------------------
def test_budget_guard_stops_the_task_and_warns(db):
    seed_permits(db, 6)
    cl = client(monthly_budget_usd=0.0025)
    f = FakeProvider(permit_handler, cost_per_call=0.001)
    s = store.TaskStats("permit_intent")                    # one permit per call, so several calls are needed
    permit_intent.run(db, cl, f, s, batch_size=1, workers=1)
    assert s.status == "budget_stopped" and s.calls < 6
    assert any("budget" in w for w in s.warnings)
    spent, _ = store.month_spend(db, "kaiser-team")
    assert spent <= 0.0025 + 1e-9


def test_budget_counts_spend_already_in_the_month(db):
    db.execute("insert into ai_outputs (client_id, task, subject_type, subject_id, input_hash, prompt_version, provider, model, status, cost_usd) "
               "values ('kaiser-team','lead_brief','parcel','1','h','v1','p','m','valid', 19.99)")
    s = store.TaskStats("lead_brief")
    g = store.BudgetGuard(db, "kaiser-team", 20, s)
    assert g.allow() is True
    s.calls, s.cost_usd = 1, 0.02                        # average call costs 0.02 -> the next one would pass 20.00
    assert g.allow() is False and s.status == "budget_stopped"
    spent, unknown = store.month_spend(db, "kaiser-team")
    assert spent == pytest.approx(19.99) and unknown == 0


def test_unknown_costs_are_flagged_not_guessed(db):
    seed_permits(db, 1)

    class NoPrice(FakeProvider):
        def complete(self, *a, **k):
            r = super().complete(*a, **k)
            r["cost_usd"] = None
            return r
    s = stats_for(db, client(), NoPrice(permit_handler), ["permit_intent"])[0]
    assert s.cost_unknown is True and any("cost unknown" in w for w in s.warnings)
    assert db.execute("select cost_usd from ai_outputs").fetchone()[0] is None
    assert db.execute("select cost_unknown, array_to_string(warnings, '|') from ai_task_runs").fetchone()[0] is True
    assert store.month_spend(db, "kaiser-team") == (0.0, 1)


# ---- skip cleanly ----------------------------------------------------------------------------------------------
def test_every_task_skips_cleanly_when_disabled_or_key_missing(db):
    seed_permits(db, 2)
    out = io.StringIO()
    res = run_ai(db, client(enabled=False), env={"LLM_API_KEY": "k"}, out=out)
    assert [r.status for r in res] == ["skipped"] * 3 and "enabled is false" in res[0].skip_reason
    res = run_ai(db, client(), env={}, out=out)                                   # key env var missing
    assert [r.status for r in res] == ["skipped"] * 3 and "LLM_API_KEY" in res[0].skip_reason
    assert db.execute("select count(*) from ai_outputs").fetchone()[0] == 0
    assert db.execute("select count(*) from ai_task_runs where status='skipped'").fetchone()[0] == 6


def test_a_client_with_no_llm_section_skips(db):
    data = load_client("kaiser-team").model_dump()
    data["llm"] = None
    res = run_ai(db, ClientConfig.model_validate(data), out=io.StringIO())
    assert all(r.status == "skipped" for r in res)


# ---- lead_brief ----------------------------------------------------------------------------------------------------
def seed_scored(db):
    add_territory(db)
    for i in range(3):
        parcel(db, f"600000000{i}", n=i)
        add_permit(db, f"600000000{i}", f"PMT-6{i}", "Replace water heater", on=AS_OF)
    add_signal(db, "6000000000", "tax_default", "distress", on=AS_OF, details={"tax_defaulted_on": "2021-06-30", "notice": "June 2026"})
    for i in range(3):
        db.execute("insert into owners (apn, owner_name, owner_occupied, absentee, out_of_state, last_sale_date, mortgage_open, provider, is_sample, as_of) "
                   "values (%s,'Sample Owner',true,false,false,'1990-01-01',false,'sample',true,%s)", (f"600000000{i}", AS_OF))
    run_score(db, CFG, AS_OF)


def brief_handler(task, system, messages):
    pk = json.loads(messages[0]["content"])
    recs = pk["records"]
    permit = next(r for r in recs if r["kind"] == "signal")
    owner = next((r for r in recs if r["kind"] == "owner"), recs[0])
    meaning = next(r for r in recs if r["kind"] == "meaning")
    return {"headline": "Remodel-type work by a long-time owner",
            "suggested_angle": "Ask whether the approved work is meant to get the home ready for sale.",
            "summary": "Work that often goes in before a sale was approved on this home. The owner has held it a long time.",
            "claims": [{"text": permit["text"], "record_ids": [permit["id"]]},
                       {"text": owner["text"].replace(" (sample data)", ""), "record_ids": [owner["id"]]},
                       {"text": meaning["text"].split(": ", 1)[1], "record_ids": [meaning["id"]]}]}


def test_lead_brief_end_to_end_cites_real_ids_and_flags_sample(db):
    seed_scored(db)
    s = stats_for(db, client(), FakeProvider(brief_handler), ["lead_brief"])[0]
    assert s.valid == 3 and s.rejected == s.invalid == 0 and s.calls == 3
    row = db.execute("select output, cited_record_ids, uses_sample, subject_type from latest_ai_outputs where subject_id='6000000000'").fetchone()
    out, cited, sample, st = row
    sig_ids = {str(r[0]) for r in db.execute("select id from signals where apn='6000000000'")}
    assert st == "parcel" and set(out["claims"][0]["record_ids"]) <= sig_ids | {"parcel:6000000000"}
    assert any(c.startswith("meaning:") for c in cited)                       # the claim citing a signal's meaning is stored
    assert cited and sample is True                                           # owner facts are sample data
    # the tax default (sensitive) never reached the model
    assert "tax" not in json.dumps(out).lower()
    s2 = stats_for(db, client(), FakeProvider(brief_handler), ["lead_brief"])[0]
    assert s2.cached == 3 and s2.calls == 0


def test_lead_brief_rejects_invented_facts(db):
    seed_scored(db)

    def liar(task, system, messages):
        d = brief_handler(task, system, messages)
        d["summary"] = "The owner of 14 Other Road has held it 45 years. Second sentence here."
        return d
    s = stats_for(db, client(), FakeProvider(liar), ["lead_brief"])[0]
    assert s.rejected == 3 and s.valid == 0 and s.calls == 6 and s.retried == 3     # primary + retry each
    assert db.execute("select count(*) from latest_ai_outputs").fetchone()[0] == 0
    assert "not in the facts" in db.execute("select rejection_reason from ai_outputs limit 1").fetchone()[0]


def test_lead_brief_selection_is_score_40_plus_the_top_200(db):
    seed_scored(db)
    rows = lead_brief.select_parcels(db, top=2, min_score=1000)
    assert len(rows) == 2 and rows[0][2] >= rows[1][2]
    assert len(lead_brief.select_parcels(db, top=0, min_score=0)) == 3
    assert len(lead_brief.select_parcels(db, top=3, min_score=0, limit=1)) == 1


# ---- weekly_brief ----------------------------------------------------------------------------------------------------
NEWS = ("This week brought steady activity across our neighborhoods, with homeowners pulling permits for everyday upgrades "
        "like new heating and cooling systems, fresh paint and plumbing work. Many of these projects keep homes comfortable and "
        "efficient for years to come. If you are curious what recent improvements mean for the value of your home, we are happy "
        "to share a simple, no-pressure summary of what is happening on your street and nearby.")


def test_weekly_facts_are_sql_computed_and_stable(db):
    seed_scored(db)
    today = date(2026, 11, 20)
    f1 = weekly_brief.compute_facts(db, today)
    assert f1 == weekly_brief.compute_facts(db, today)
    assert f1["week"] == {"start": "2026-11-13", "end": "2026-11-20"} and list(f1["neighborhoods"]) == ["La Jolla"]
    t = f1["territory"]
    assert t["new_pre_sale_permits"] == 3 and t["tax_default_new_this_week"] == 1       # all dated 2026-11-18, inside the week
    assert f1["baseline"]["kind"] == "none" and t["new_strong_leads"] is None and t["top_movers"] == []
    assert t["tax_default_total"] == 1
    assert t["new_permits_by_type"] == {"remodel or cosmetic permits": 3}               # Phase 5H: new signals by type, per neighborhood
    assert f1["neighborhoods"]["La Jolla"]["new_permits_by_type"] == {"remodel or cosmetic permits": 3}
    assert f1["scoring_model_changed"] is False
    assert all(set(x) == {"rank", "what", "neighborhood", "date"} for x in f1["top_new_signals"])       # no address, no parcel number


def test_weekly_brief_end_to_end(db):
    seed_scored(db)
    today = date(2026, 11, 20)

    def handler(task, system, messages):
        facts = json.loads(messages[0]["content"])
        n = facts["territory"]["new_this_week"]["remodel or cosmetic permits"]
        return {"title": "A steady week", "intro": f"We saw {n} new pre-sale permits. Activity looks steady.",
                "sections": [{"neighborhood": "La Jolla", "bullets": [f"{n} new pre-sale permits."]}], "newsletter_paragraph": NEWS}
    s = stats_for(db, client(), FakeProvider(handler), ["weekly_brief"], today=today)[0]
    assert s.valid == 1, db.execute("select rejection_reason from ai_outputs").fetchall()
    out, sid, st = db.execute("select output, subject_id, subject_type from latest_ai_outputs where task='weekly_brief'").fetchone()
    assert sid == "2026-11-13" and st == "territory" and out["facts"]["week"]["end"] == "2026-11-20"
    assert stats_for(db, client(), FakeProvider(handler), ["weekly_brief"], today=today)[0].cached == 1


def test_weekly_brief_rejects_an_address_in_the_newsletter(db):
    seed_scored(db)
    bad = NEWS + " Visit 123 Prospect St."

    def handler(task, system, messages):
        return {"title": "t", "intro": "One. Two.", "sections": [{"neighborhood": "La Jolla", "bullets": ["x"]}], "newsletter_paragraph": bad}
    s = stats_for(db, client(), FakeProvider(handler), ["weekly_brief"], today=date(2026, 11, 20))[0]
    assert s.rejected == 1 and db.execute("select count(*) from latest_ai_outputs").fetchone()[0] == 0


def test_one_failing_task_does_not_stop_the_others(db):
    seed_scored(db)

    class Boom(FakeProvider):
        def complete(self, task, *a, **k):
            if task == "permit_intent":
                raise RuntimeError("boom")
            return super().complete(task, *a, **k)
    res = stats_for(db, client(), Boom(brief_handler), ["permit_intent", "lead_brief"])
    assert res[0].status == "failed" and res[1].status == "success" and res[1].valid == 3


def test_run_py_flags():
    import territory.run as r
    with pytest.raises(SystemExit):
        r.main(["--client", "kaiser-team", "--only-ai", "--skip-ai"])
    with pytest.raises(SystemExit):
        r.main(["--client", "kaiser-team"])
    with pytest.raises(SystemExit):
        r.main(["--client", "kaiser-team", "--source", "all", "--tasks", "lead_brief"])      # --tasks needs --only-ai
    with pytest.raises(SystemExit):
        r.main(["--client", "kaiser-team", "--only-ai", "--tasks", "scores"])                 # unknown task


def test_only_ai_tasks_runs_just_the_named_tasks(db, monkeypatch):
    import territory.run as r
    seen = {}
    monkeypatch.setattr("territory.llm.runner.run_ai", lambda conn, client, tasks=None, **kw: seen.setdefault("tasks", tasks))
    monkeypatch.setattr("territory.db.refresh_dashboard_aggregates", lambda: True)
    assert r.main(["--client", "kaiser-team", "--only-ai", "--tasks", "lead_brief,weekly_brief"]) == 0
    assert seen["tasks"] == ["lead_brief", "weekly_brief"]


def test_weekly_facts_only_compare_runs_of_the_same_scoring_model(db):
    """After a model change a score that moved because the rules moved is not news (Phase 5G, v0.3 -> v0.4)."""
    seed_scored(db)
    today = date(2026, 11, 20)
    old = db.execute("select apn, score from latest_scores").fetchall()
    for apn, score in old:                     # an older run under the previous model, with very different scores
        db.execute("insert into scores (apn, score, components, reason_text, recipe_matches, model_version, scored_at, "
                   "uses_sample_data, primary_recipe) values (%s,%s,'[]','x','{}','v0.3-handset','2026-11-01T00:00:00Z',false,null)",
                   (apn, min(100, score + 30)))
    f = weekly_brief.compute_facts(db, today)
    assert f["baseline"]["kind"] == "none" and f["territory"]["top_movers"] == [] and f["territory"]["new_strong_leads"] is None
    # a second run of the SAME version is compared normally
    run_score(db, CFG, AS_OF)
    assert weekly_brief.compute_facts(db, today)["baseline"]["kind"] == "earliest_available"


def test_editing_a_prompt_without_bumping_its_version_does_not_serve_cached_briefs(db, monkeypatch):
    """Phase 5G: the prompt's text is part of the cache key for lead_brief and weekly_brief."""
    seed_scored(db)
    assert stats_for(db, client(), FakeProvider(brief_handler), ["lead_brief"])[0].valid == 3
    assert stats_for(db, client(), FakeProvider(brief_handler), ["lead_brief"])[0].cached == 3
    real = lead_brief.load_prompt
    monkeypatch.setattr(lead_brief, "load_prompt", lambda task, *a, **k: (real(task)[0] + "\nAn extra rule.", real(task)[1]))
    s = stats_for(db, client(), FakeProvider(brief_handler), ["lead_brief"])[0]
    assert s.cached == 0 and s.valid == 3                                        # same version label, new text: asked again


def test_weekly_model_view_drops_comparisons_when_the_scoring_model_changed():
    base = {"strong_leads_now": 7, "new_strong_leads": 3, "recipe_counts": {"Pre-list prep": {"now": 16, "before": 10, "change": 6}},
            "new_pre_sale_permits": 6, "tax_default_new_this_week": 0, "tax_default_total": 39, "new_str_removals": 1,
            "new_permits_by_type": {"remodel or cosmetic permits": 6}, "top_movers": [{"address": "1 A St", "score_before": 1, "score_now": 2, "change": 1}]}
    facts = {"week": {"start": "a", "end": "b"}, "territory": base, "neighborhoods": {"La Jolla": base}, "top_new_signals": [{"rank": 1}]}
    v = weekly_brief.model_view(facts)
    assert v["territory"]["new_this_week"] == {"remodel or cosmetic permits": 6, "short-term rental licenses removed": 1}
    assert v["territory"]["new_strong_leads"] == 3 and "changes_by_home_type" in v["territory"] and "scoring_model_changed" not in v
    changed = weekly_brief.model_view({**facts, "scoring_model_changed": True})
    assert changed["scoring_model_changed"] is True
    for k in ("new_strong_leads", "changes_by_home_type", "top_movers"):
        assert k not in changed["territory"] and k not in changed["neighborhoods"]["La Jolla"]
    assert changed["territory"]["strong_leads_now"] == 7 and changed["top_new_signals"] == [{"rank": 1}]


def test_weekly_validate_requires_the_recalculation_sentence_exactly_once_after_a_model_change():
    facts = {"scoring_model_changed": True, "neighborhoods": {"La Jolla": {}}, "week": {}, "territory": {"top_movers": []}}
    mk = lambda intro, bullets=("A bullet.",): weekly_brief.WeeklyOut(title="Busy week", intro=intro, newsletter_paragraph=NEWS,
                                                                     sections=[weekly_brief.Section(neighborhood="La Jolla", bullets=list(bullets))])
    assert not [p for p in weekly_brief.validate(mk("Lead counts were recalculated this week."), facts) if "recalculat" in p]
    assert any("recalculat" in p for p in weekly_brief.validate(mk("Busy week."), facts))
    assert any("recalculat" in p for p in weekly_brief.validate(mk("Counts were recalculated.", ["Recalculated again."]), facts))
    assert any("did not change" in p for p in weekly_brief.validate(mk("Counts were recalculated."), {**facts, "scoring_model_changed": False}))


def test_weekly_validate_rejects_the_same_count_stated_twice():
    facts = {"scoring_model_changed": False, "neighborhoods": {"La Jolla": {}}, "week": {}, "territory": {"top_movers": []},
             "x": "4 5"}
    out = weekly_brief.WeeklyOut(title="Permits lead the week", intro="La Jolla has 4 new remodel permits. That is 4 remodel permits approved.",
                                 newsletter_paragraph=NEWS, sections=[weekly_brief.Section(neighborhood="La Jolla", bullets=["Fine."])])
    assert any("repeats the count 4" in p for p in weekly_brief.validate(out, facts))
