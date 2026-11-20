"""Phase 5G: every AI task retries once with the rejection reason appended, then calls the task's fallback model.
Empty output counts as rejected. Every attempt is stored; only the final valid one is shown."""
import json

import pytest
from pydantic import BaseModel

from test_llm_tasks_db import (add_permit, brief_handler, client, seed_permits, seed_scored, stats_for)
from helpers import add_territory
from test_scoring_db import parcel
from territory.llm import attempts as at
from territory.llm.base import LLMError
from territory.llm.fake import FakeProvider
from territory.llm.tasks import permit_intent


class Out(BaseModel):
    text: str


class PerModel(FakeProvider):
    """Replies chosen by the model the call asked for: {model: handler or list of replies}."""

    def __init__(self, plan, **kw):
        super().__init__(**kw)
        self.plan = {m: (list(v) if isinstance(v, list) else v) for m, v in plan.items()}

    def complete(self, task, system, messages, json_schema, model=None):
        self.calls.append({"task": task, "system": system, "messages": messages, "model": model})
        p = self.plan[model]
        reply = p.pop(0) if isinstance(p, list) else p(task, system, messages)
        if isinstance(reply, Exception):
            raise reply
        raw = reply if isinstance(reply, str) else json.dumps(reply)
        try:
            out = json.loads(raw)
        except ValueError:
            out = None
        return {"output": out, "raw": raw, "provider": "fake", "model": model, "input_tokens": 10, "output_tokens": 5,
                "cost_usd": 0.001, "latency_ms": 1}


def ev(v):
    return at.Evaluation(None, ["text must say ok"], []) if v.text != "ok" else at.Evaluation({"text": "ok"}, [], [])


def chain(plan, fallback="fb"):
    p = PerModel(plan)
    return p, at.run_chain(p, "t", "sys", "user text", Out, ev, "main", fallback)


# ---- the chain -------------------------------------------------------------------------------------------------
def test_valid_first_time_makes_one_call():
    p, c = chain({"main": [{"text": "ok"}]})
    assert [(a.n, a.role, a.status) for a in c] == [(1, "primary", "valid")] and len(p.calls) == 1


def test_a_rejected_reply_is_retried_once_with_the_reason_appended():
    p, c = chain({"main": [{"text": "bad"}, {"text": "ok"}]})
    assert [(a.role, a.status) for a in c] == [("primary", "rejected"), ("retry", "valid")]
    retry = p.calls[1]
    assert retry["model"] == "main" and [m["role"] for m in retry["messages"]] == ["user", "assistant", "user"]
    assert "text must say ok" in retry["messages"][2]["content"] and retry["messages"][1]["content"] == '{"text": "bad"}'


def test_still_failing_after_the_retry_calls_the_fallback_model_fresh():
    p, c = chain({"main": [{"text": "bad"}, {"text": "worse"}], "fb": [{"text": "ok"}]})
    assert [(a.n, a.role, a.status, a.model) for a in c] == [
        (1, "primary", "rejected", "main"), (2, "retry", "rejected", "main"), (3, "fallback", "valid", "fb")]
    assert len(p.calls[2]["messages"]) == 1                       # the fallback starts fresh, no history


def test_empty_output_counts_as_rejected_and_is_retried():
    p, c = chain({"main": ["", {"text": "ok"}]})
    assert (c[0].status, c[0].problems) == ("rejected", ["empty output"]) and c[1].status == "valid"
    # nothing to echo back for an empty reply: the reason is appended to the user message instead
    assert [m["role"] for m in p.calls[1]["messages"]] == ["user"] and "empty output" in p.calls[1]["messages"][0]["content"]
    p, c = chain({"main": [{"text": "  "}, {"text": "  "}], "fb": [{"text": ""}]})
    assert [a.status for a in c] == ["rejected"] * 3 and all(a.problems == ["empty output"] for a in c)


def test_invalid_json_is_invalid_not_rejected():
    _, c = chain({"main": ["not json", {"text": "ok"}]})
    assert c[0].status == "invalid" and c[1].status == "valid"


def test_a_provider_error_skips_the_retry_and_goes_to_the_fallback():
    p, c = chain({"main": [LLMError("HTTP 503")], "fb": [{"text": "ok"}]})
    assert [(a.role, a.status) for a in c] == [("primary", "invalid"), ("fallback", "valid")]
    assert c[0].provider_error and "HTTP 503" in c[0].reason and len(p.calls) == 2


def test_no_fallback_configured_stops_after_the_retry():
    p, c = chain({"main": [{"text": "bad"}, {"text": "bad"}]}, fallback=None)
    assert len(c) == 2 and c[-1].status == "rejected"


# ---- lead_brief end to end ---------------------------------------------------------------------------------------
def test_lead_brief_retries_then_falls_back_and_stores_every_attempt(db):
    seed_scored(db)
    bad = lambda t, s, m: {**brief_handler(t, s, m), "summary": "Only one sentence."}
    cl = client(tasks={"lead_brief": {"fallback_model": "fb-model"}})
    f = PerModel({"fake-model": bad, "fb-model": brief_handler})
    s = stats_for(db, cl, f, ["lead_brief"])[0]
    assert (s.valid, s.rejected, s.invalid, s.calls, s.retried, s.fallbacks) == (3, 0, 0, 9, 3, 3)
    rows = db.execute("select attempt, is_fallback, status, model from ai_outputs where subject_id='6000000000' order by attempt").fetchall()
    assert rows == [(1, False, "rejected", "fake-model"), (2, False, "rejected", "fake-model"), (3, True, "valid", "fb-model")]
    shown = db.execute("select model, status from latest_ai_outputs where subject_id='6000000000'").fetchall()
    assert shown == [("fb-model", "valid")]                                  # only the final valid one is shown
    assert "sentences" in db.execute("select rejection_reason from ai_outputs where attempt=1 limit 1").fetchone()[0]
    run = db.execute("select valid, retried, fallbacks from ai_task_runs where task='lead_brief'").fetchone()
    assert run == (3, 3, 3)


def test_lead_brief_with_everything_failing_shows_nothing(db):
    seed_scored(db)
    cl = client(tasks={"lead_brief": {"fallback_model": "fb-model"}})
    f = PerModel({"fake-model": [""] * 6, "fb-model": [""] * 3})
    s = stats_for(db, cl, f, ["lead_brief"])[0]
    assert (s.valid, s.rejected) == (0, 3) and s.fallbacks == 3
    assert db.execute("select count(*) from ai_outputs where status='rejected' and rejection_reason='empty output'").fetchone()[0] == 9
    assert db.execute("select count(*) from latest_ai_outputs").fetchone()[0] == 0


def test_a_good_first_reply_never_touches_the_fallback(db):
    seed_scored(db)
    cl = client(tasks={"lead_brief": {"fallback_model": "fb-model"}})
    f = PerModel({"fake-model": brief_handler})
    s = stats_for(db, cl, f, ["lead_brief"])[0]
    assert (s.valid, s.calls, s.retried, s.fallbacks) == (3, 3, 0, 0) and all(c["model"] == "fake-model" for c in f.calls)


# ---- permit_intent: only the failed permits are asked again ----------------------------------------------------
def good(it, quote=None):
    return {"id": it["id"], "intent": "maintenance", "scope_tags": [], "confidence": 0.9,
            "quote": quote or " ".join(it["description"].split()[:3]), "reason": "r"}


def test_permit_intent_retries_and_falls_back_only_for_the_failed_permits(db):
    seed_permits(db, 3)
    seen = {}

    def main(task, system, messages):
        items = json.loads(messages[0]["content"])
        seen.setdefault("main", []).append(messages[-1]["content"] if len(messages) > 1 else "first call")
        # id 2 never gets a quote that is in the text, in any attempt; id 3 is fixed by the retry
        retried = len(messages) > 1
        return {"items": [good(it, "not in the text" if it["id"] == 2 else None) for it in items
                          if not (it["id"] == 3 and not retried)]}

    def fb(task, system, messages):
        items = json.loads(messages[0]["content"])
        seen["fb"] = [it["id"] for it in items]
        return {"items": [good(it) for it in items]}

    cl = client(tasks={"permit_intent": {"fallback_model": "fb-model"}})
    s = stats_for(db, cl, PerModel({"fake-model": main, "fb-model": fb}), ["permit_intent"])[0]
    assert (s.valid, s.rejected, s.invalid, s.calls, s.retried, s.fallbacks) == (3, 0, 0, 3, 2, 1)
    retry_note = seen["main"][1]                                  # the retry asked only for the failed permits
    assert seen["main"][0] == "first call" and "- id 2:" in retry_note and "- id 3:" in retry_note and "- id 1:" not in retry_note
    assert "quoted words" in retry_note and "missing from the reply" in retry_note   # the reasons are appended
    assert seen["fb"] == [1]                                      # the fallback got one permit, renumbered to id 1
    by = {sid: (a, fbk, st) for sid, a, fbk, st in db.execute(
        "select subject_id, attempt, is_fallback, status from ai_outputs order by subject_id, attempt").fetchall() if st == "valid"}
    assert by == {"PMT-0": (1, False, "valid"), "PMT-1": (3, True, "valid"), "PMT-2": (2, False, "valid")}
    assert db.execute("select count(*) from latest_ai_outputs").fetchone()[0] == 3
    assert db.execute("select count(*) from ai_outputs where status <> 'valid'").fetchone()[0] == 3


def test_permit_intent_empty_batch_reply_is_rejected_then_retried(db):
    seed_permits(db, 2)
    f = PerModel({"fake-model": ["", lambda *a: None]})
    f.plan["fake-model"] = ["", json.dumps({"items": [good({"id": i, "description": f"Replace furnace and ductwork at unit {i - 1} of the house"}) for i in (1, 2)]})]
    s = stats_for(db, client(), f, ["permit_intent"])[0]
    assert (s.valid, s.calls) == (2, 2)
    assert db.execute("select count(*) from ai_outputs where status='rejected' and rejection_reason='empty output'").fetchone()[0] == 2


def test_the_configured_fallbacks_are_the_ones_from_the_model_selection_report():
    from territory.config import load_client
    llm = load_client("kaiser-team").llm
    assert llm.fallback_model_for("lead_brief") == llm.fallback_model_for("weekly_brief") == "qwen/qwen3.6-35b-a3b"
    assert llm.fallback_model_for("permit_intent") == "qwen/qwen3.6-27b"
