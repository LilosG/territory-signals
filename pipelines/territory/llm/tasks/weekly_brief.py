"""weekly_brief: SQL computes the week's facts; AI writes only the prose around them."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from territory.config import ClientConfig
from territory.homeowner_text import check_homeowner_text
from territory.llm import attempts as at, store
from territory.llm.base import Provider
from territory.llm.prompts import load_prompt
from territory.llm.tasks.lead_brief import SENSITIVE_RECIPES
from territory.llm.validators import check_addresses, check_numbers, check_speculation, strings_of
from territory.scoring_engine import load_scoring_config

TASK = "weekly_brief"
STRONG = 60                      # Warm band and above (config/scoring.yaml score_bands)


class Section(BaseModel):
    neighborhood: str
    bullets: list[str]


class WeeklyOut(BaseModel):
    title: str
    intro: str
    sections: list[Section]
    newsletter_paragraph: str


def week_start(today: date) -> date:
    return today - timedelta(days=7)


def _runs(conn, start: datetime) -> tuple[Any, Any, str]:
    """(latest scoring run, baseline scoring run, kind). Baseline = last run at or before the week start; if there is
    none, the earliest earlier run available (kind says which); None when only one run exists."""
    latest = conn.execute("select max(scored_at) from scores").fetchone()[0]
    base = conn.execute("select max(scored_at) from scores where scored_at <= %s", (start,)).fetchone()[0]
    if base is not None and base < latest:
        return latest, base, "week_start"
    first = conn.execute("select min(scored_at) from scores").fetchone()[0]
    if first is not None and first < latest:
        return latest, first, "earliest_available"
    return latest, None, "none"


def compute_facts(conn, today: date, scoring_cfg: dict | None = None, hoods: list[str] | None = None) -> dict:
    """Everything the briefing may say, from SQL. Deterministic for a given database state."""
    cfg = scoring_cfg or load_scoring_config()
    start_d, end_d = week_start(today), today
    start = datetime.combine(start_d, datetime.min.time(), tzinfo=timezone.utc)
    latest, base, kind = _runs(conn, start)
    labels = {k: v.get("label", k) for k, v in cfg["recipes"].items() if k not in SENSITIVE_RECIPES}
    hoods = hoods or [r[0] for r in conn.execute("select name from neighborhoods order by name")]
    facts: dict[str, Any] = {
        "week": {"start": start_d.isoformat(), "end": end_d.isoformat()},
        "baseline": {"kind": kind, "compared_with": base.date().isoformat() if base else None},
        "territory": None, "neighborhoods": {},
    }

    def scope_facts(hood: str | None) -> dict[str, Any]:
        h = hood
        strong_now = conn.execute(
            "select count(*) from scores s join parcels p using (apn) where s.scored_at=%s and s.score>=%s "
            "and (%s::text is null or coalesce(p.neighborhood,p.planning_area)=%s)", (latest, STRONG, h, h)).fetchone()[0]
        new_strong = None
        if base is not None:
            new_strong = conn.execute(
                """select count(*) from scores s join parcels p using (apn)
                    where s.scored_at=%(l)s and s.score>=%(t)s and (%(h)s::text is null or coalesce(p.neighborhood,p.planning_area)=%(h)s)
                      and not exists (select 1 from scores b where b.scored_at=%(b)s and b.apn=s.apn and b.score>=%(t)s)""",
                {"l": latest, "b": base, "t": STRONG, "h": h}).fetchone()[0]
        recipes: dict[str, dict] = {}
        for rk, label in labels.items():
            now = conn.execute(
                "select count(*) from scores s join parcels p using (apn) where s.scored_at=%s and %s = any(s.recipe_matches) "
                "and (%s::text is null or coalesce(p.neighborhood,p.planning_area)=%s)", (latest, rk, h, h)).fetchone()[0]
            before = None if base is None else conn.execute(
                "select count(*) from scores s join parcels p using (apn) where s.scored_at=%s and %s = any(s.recipe_matches) "
                "and (%s::text is null or coalesce(p.neighborhood,p.planning_area)=%s)", (base, rk, h, h)).fetchone()[0]
            if now or before:
                recipes[label] = {"now": now, "before": before, "change": None if before is None else now - before}
        permits = conn.execute(
            "select count(distinct s.source_record_id) from signals s join parcels p using (apn) "
            "where s.signal_type='permit_approved' and s.signal_group='pre_sale_prep' and s.superseded_by is null "
            "and s.signal_date > %s and s.signal_date <= %s and (%s::text is null or coalesce(p.neighborhood,p.planning_area)=%s)",
            (start_d, end_d, h, h)).fetchone()[0]
        tax_new, tax_total = conn.execute(
            "select count(*) filter (where s.signal_date > %s and s.signal_date <= %s), count(*) from signals s join parcels p using (apn) "
            "where s.signal_type='tax_default' and s.superseded_by is null and (%s::text is null or coalesce(p.neighborhood,p.planning_area)=%s)",
            (start_d, end_d, h, h)).fetchone()
        str_new = conn.execute(
            "select count(*) from signals s join parcels p using (apn) where s.signal_type='stro_license_removed' "
            "and s.superseded_by is null and s.signal_date > %s and s.signal_date <= %s "
            "and (%s::text is null or coalesce(p.neighborhood,p.planning_area)=%s)", (start_d, end_d, h, h)).fetchone()[0]
        movers = []
        if base is not None:
            movers = [{"address": r[0], "neighborhood": r[1], "score_before": r[2], "score_now": r[3], "change": r[3] - r[2]}
                      for r in conn.execute(
                """select p.situs_address, coalesce(p.neighborhood,p.planning_area), b.score, s.score
                     from scores s join scores b on b.apn=s.apn and b.scored_at=%(b)s join parcels p on p.apn=s.apn
                    where s.scored_at=%(l)s and s.score<>b.score and (%(h)s::text is null or coalesce(p.neighborhood,p.planning_area)=%(h)s)
                    order by abs(s.score-b.score) desc, p.apn limit 5""", {"l": latest, "b": base, "h": h})]
        return {"strong_leads_now": strong_now, "new_strong_leads": new_strong, "recipe_counts": recipes,
                "new_pre_sale_permits": permits, "tax_default_new_this_week": tax_new, "tax_default_total": tax_total,
                "new_str_removals": str_new, "top_movers": movers}

    facts["territory"] = scope_facts(None)
    for hname in hoods:
        facts["neighborhoods"][hname] = scope_facts(hname)
    return facts


def recipe_label_set() -> set[str]:
    cfg = load_scoring_config()
    return {v.get("label", k) for k, v in cfg["recipes"].items()}


def validate(out: WeeklyOut, facts: dict) -> list[str]:
    problems: list[str] = []
    texts = [out.title, out.intro, out.newsletter_paragraph] + [b for s in out.sections for b in [s.neighborhood, *s.bullets]]
    for s in out.sections:
        if len(s.bullets) > 4:
            problems.append(f"{s.neighborhood}: more than 4 bullets")
        if s.neighborhood not in facts["neighborhoods"]:
            problems.append(f"unknown neighborhood {s.neighborhood!r}")
    if not out.sections:
        problems.append("no sections")
    nsent = len([x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", out.intro.strip()) if x])
    if nsent != 2:
        problems.append(f"intro has {nsent} sentences (need 2)")
    nw = len(out.newsletter_paragraph.split())
    if not 60 <= nw <= 90:
        problems.append(f"newsletter paragraph has {nw} words (need 60 to 90)")
    if re.search(r"tax|default|delinquen", out.title + " " + out.intro, re.I):
        problems.append("title or intro mentions tax-default (neighborhood bullets only)")
    problems += check_numbers(texts, facts)
    problems += check_speculation(texts, facts)
    problems += [f"newsletter: {p}" for p in check_homeowner_text(out.newsletter_paragraph, recipe_labels=recipe_label_set())]
    mover_addrs = [m["address"] for m in facts["territory"]["top_movers"] if m.get("address")]
    for a in mover_addrs:
        if a and a.lower() in out.newsletter_paragraph.lower():
            problems.append("newsletter names a property address")
    problems += check_addresses([out.newsletter_paragraph], [])
    return problems


def evaluate(out: WeeklyOut, facts: dict, sid: str = "") -> at.Evaluation:
    problems = validate(out, facts)
    return at.Evaluation(out.model_dump() if not problems else None, problems, [f"week:{sid}"] if sid else [])


def run(conn, client: ClientConfig, provider: Provider, stats: store.TaskStats, today: date | None = None) -> None:
    system, version = load_prompt(TASK)
    model = client.llm.model_for(TASK)
    stats.model = model
    today = today or date.today()
    facts = compute_facts(conn, today)
    sid = week_start(today).isoformat()
    ihash = store.input_hash(facts)
    if store.find_cached(conn, client.client_id, TASK, sid, ihash, version):
        stats.cached += 1
        return
    guard = store.BudgetGuard(conn, client.client_id, client.llm.monthly_budget_usd, stats)
    if not guard.allow():
        return
    chain = at.run_chain(provider, TASK, system, json.dumps(facts, ensure_ascii=False, indent=1), WeeklyOut,
                         lambda v: evaluate(v, facts, sid), model, client.llm.fallback_model_for(TASK))
    at.record(stats, chain, f"week {sid}")
    for a in chain:            # keep the facts the numbers came from next to the stored prose
        if a.status == "valid":
            a.output = {**a.output, "facts": facts}
    store.insert_outputs(conn, at.rows(chain, client.client_id, TASK, "territory", sid, ihash, version))
