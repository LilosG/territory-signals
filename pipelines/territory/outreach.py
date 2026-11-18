"""Outreach draft generator (Phase 5A, D10, D11).

    python -m territory.outreach --client kaiser-team [--channels mail,email,call_task] [--drafts N] [--dry-run]

Picks the top parcels from latest_scores (latest scoring run) that match at least one enabled recipe, are not
suppressed and have no outreach row inside the cooldown, chooses the template by the primary recipe and the
channel, and writes outreach rows (status draft, or awaiting_approval for approval-required recipes).

Deterministic: templates + facts already in the database. Mode `preview` never sends anything and never calls
an external service (no network library is imported here); the only I/O is the database.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from dateutil.relativedelta import relativedelta
from psycopg.types.json import Jsonb

from territory.config import ClientConfig, TeamMember, load_client
from territory.db import connect
from territory.outreach_render import CHANNEL_FILE, SAMPLE_BANNER, load_template, render
from territory.salutation import format_salutation, pretty_address
from territory.scoring_engine import load_scoring_config

DEFAULT_CHANNELS = ("mail",)
# Owner fields in scoring conditions -> owner_field values of the components they produce.
_OWNER_FIELDS = {"years_owned": {"last_sale_date"}, "absentee": {"absentee", "out_of_state"}}


# ---------------------------------------------------------------------------------------
# recipe choice
# ---------------------------------------------------------------------------------------
def _refs(cond: Mapping[str, Any], sig: list, own: set) -> None:
    for k in ("all", "any"):
        for c in cond.get(k, ()):
            _refs(c, sig, own)
    if "not" in cond:
        _refs(cond["not"], sig, own)
    if "signal" in cond:
        sig.append((cond["signal"], cond.get("group")))
    if "owner" in cond:
        own.update(_OWNER_FIELDS.get(cond["owner"], {cond["owner"]}))


def recipe_contribution(recipe_cfg: Mapping[str, Any], components: list[Mapping[str, Any]]) -> float:
    """Points of the components a recipe's conditions refer to (its signals and owner fields)."""
    sig: list = []
    own: set = set()
    _refs(recipe_cfg["when"], sig, own)
    total = 0.0
    for c in components:
        if c.get("kind") == "signal" and any(
                c.get("signal_type") == t and (g is None or c.get("group") == g) for t, g in sig):
            total += c["contribution"]
        elif c.get("kind") == "owner" and c.get("owner_field") in own:
            total += c["contribution"]
    return total


def primary_recipe(matches: list[str], enabled: list[str], scoring_cfg: Mapping[str, Any],
                   components: list[Mapping[str, Any]]) -> Optional[str]:
    """The enabled matched recipe with the highest contributing components; ties go to config order."""
    order = list(scoring_cfg["recipes"])
    cands = [r for r in matches if r in enabled and r in scoring_cfg["recipes"]]
    if not cands:
        return None
    return max(cands, key=lambda r: (recipe_contribution(scoring_cfg["recipes"][r], components), -order.index(r)))


# ---------------------------------------------------------------------------------------
# addresses
# ---------------------------------------------------------------------------------------
def _norm_addr(a: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", a.upper())).strip()


def same_address(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    x, y = _norm_addr(a), _norm_addr(b)
    return x.startswith(y) or y.startswith(x)


def mailing_for(owner_mailing: Optional[str], situs: Optional[str], zip_: Optional[str]) -> Optional[str]:
    """owners.mailing_address when present and different from the situs address, otherwise the situs address
    (the City of San Diego territory: city and state are added to the situs line)."""
    if owner_mailing and owner_mailing.strip() and not same_address(owner_mailing, situs):
        return owner_mailing.strip()
    if not situs:
        return None
    return f"{pretty_address(situs)}, San Diego, CA{' ' + zip_ if zip_ else ''}"


# ---------------------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Candidate:
    apn: str
    score: int
    components: list
    reason_text: str
    recipe_matches: list
    model_version: str
    uses_sample_data: bool
    situs_address: Optional[str]
    zip: Optional[str]
    neighborhood: Optional[str]


def select_candidates(conn, client: ClientConfig, scoring_cfg: Mapping[str, Any], now: datetime,
                      limit: int) -> list[Candidate]:
    enabled = [r for r in client.enabled_recipes() if scoring_cfg["recipes"].get(r, {}).get("active") is not False]
    today = now.date()
    sale_cutoff = today - relativedelta(months=scoring_cfg["suppression"]["recent_sale_months"])
    cooldown_start = now - timedelta(days=client.outreach.cooldown_days)
    rows = conn.execute(
        """
        select s.apn, s.score, s.components, s.reason_text, s.recipe_matches, s.model_version,
               s.uses_sample_data, p.situs_address, p.zip, coalesce(p.neighborhood, p.planning_area)
        from latest_scores s
        join parcels p on p.apn = s.apn
        where s.scored_at = (select max(scored_at) from scores)
          and s.recipe_matches && %(enabled)s::text[]
          and not exists (select 1 from outreach o where o.apn = s.apn and o.created_at >= %(cooldown)s)
          and not exists (select 1 from suppressions x where x.apn = s.apn
                          and (x.until_date is null or x.until_date >= %(today)s))
          and not exists (select 1 from sales_history h where h.apn = s.apn
                          and h.sale_date >= %(sale_cutoff)s and h.sale_date <= %(today)s)
        order by s.score desc, s.apn
        limit %(limit)s
        """, {"enabled": enabled, "cooldown": cooldown_start, "today": today, "sale_cutoff": sale_cutoff,
              "limit": limit}).fetchall()
    return [Candidate(*r) for r in rows]


def load_owner_rows(conn, apns: list[str]) -> dict[str, dict[str, Any]]:
    """Latest owners row per parcel (same ordering the scorer uses)."""
    out = {}
    for r in conn.execute(
            "select distinct on (apn) apn, id, owner_name, mailing_address, is_sample, provider, as_of "
            "from owners where apn = any(%s) "
            "order by apn, as_of desc, (provider = 'attom') desc, created_at desc", (apns,)):
        out[r[0]] = {"owner_id": str(r[1]), "owner_name": r[2], "mailing_address": r[3], "is_sample": r[4],
                     "provider": r[5], "as_of": str(r[6])}
    return out


def pick_agents(client: ClientConfig) -> list[TeamMember]:
    return sorted((m for m in client.team_members if m.role == "agent"), key=lambda m: m.email)


# ---------------------------------------------------------------------------------------
# drafts
# ---------------------------------------------------------------------------------------
def component_fact(c: Mapping[str, Any]) -> dict[str, Any]:
    out = {"kind": "component", "key": c["key"], "source_key": c.get("source_key"),
           "source_record_id": c.get("source_record_id"), "confidence": c.get("confidence"),
           "match_method": c.get("match_method"), "is_sample": c.get("is_sample", False),
           "is_estimate": c.get("is_estimate", False), "facts": c.get("facts", {})}
    if c.get("signal_id"):
        out["signal_id"] = c["signal_id"]
    if c.get("owner_field"):
        out["owner_field"] = c["owner_field"]
    return out


def build_draft(cand: Candidate, owner: Optional[Mapping[str, Any]], recipe: str, channel: str,
                client: ClientConfig, agent: Optional[TeamMember]) -> dict[str, Any]:
    owner = owner or {}
    sal = format_salutation(owner.get("owner_name"), cand.situs_address, bool(owner.get("is_sample")))
    template = load_template(recipe, channel)
    rendered = render(channel, template, sal.text, cand.neighborhood or "the area",
                      pretty_address(cand.situs_address), agent, client.team_profile)
    # source_facts: exactly the facts the rendered text uses. A template lists the component keys it relies
    # on; the owner name counts only when the text opens with it (mail and email, not the address fallback).
    facts = [component_fact(c) for c in cand.components
             if c["contribution"] > 0 and c["key"].split(":")[0] in template.facts]
    if sal.uses_owner_name and channel in ("mail", "email"):
        facts.append({"kind": "owner_field", "owner_field": "owner_name", "owner_id": owner.get("owner_id"),
                      "value": owner.get("owner_name"), "provider": owner.get("provider"),
                      "as_of": owner.get("as_of"), "is_sample": bool(owner.get("is_sample"))})
    sample = bool(cand.uses_sample_data or owner.get("is_sample"))
    status = "awaiting_approval" if recipe in client.outreach.approval_required_recipes else "draft"
    return {
        "apn": cand.apn, "channel": channel, "status": status, "recipe": recipe,
        "content": (SAMPLE_BANNER + "\n\n" if sample else "") + rendered.text,
        "text": rendered.text, "subject": rendered.subject, "source_facts": facts,
        "template_key": rendered.template_key, "model_version": cand.model_version,
        "mailing_address": mailing_for(owner.get("mailing_address"), cand.situs_address, cand.zip),
        "salutation": sal.text, "assigned_to": agent.email if agent else None,
        "blocked_reason": rendered.blocked_reason, "uses_sample_data": sample, "score": cand.score,
        "reason_text": cand.reason_text,
    }


INSERT_SQL = (
    "insert into outreach (apn, channel, status, content, source_facts, recipe, assigned_to, mailing_address, "
    "salutation, template_key, model_version, blocked_reason, uses_sample_data) "
    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")


def run_outreach(conn, client: ClientConfig, scoring_cfg: Mapping[str, Any] | None = None,
                 channels: tuple[str, ...] = DEFAULT_CHANNELS, drafts: int | None = None,
                 now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    if client.outreach.mode != "preview":      # pragma: no cover - the config model only allows preview
        raise RuntimeError("only outreach mode 'preview' exists; nothing is ever sent")
    for ch in channels:
        if ch not in CHANNEL_FILE:
            raise ValueError(f"unknown channel {ch!r}; use {sorted(CHANNEL_FILE)}")
    scoring_cfg = scoring_cfg or load_scoring_config()
    now = now or datetime.now(timezone.utc)
    cands = select_candidates(conn, client, scoring_cfg, now, drafts or client.outreach.drafts_per_run)
    owners = load_owner_rows(conn, [c.apn for c in cands])
    agents = pick_agents(client)
    offset = conn.execute("select count(distinct apn) from outreach where assigned_to is not null").fetchone()[0]
    enabled = client.enabled_recipes()
    out: list[dict[str, Any]] = []
    for i, cand in enumerate(cands):
        recipe = primary_recipe(cand.recipe_matches, enabled, scoring_cfg, cand.components)
        agent = agents[(offset + i) % len(agents)] if agents else None
        for ch in channels:
            out.append(build_draft(cand, owners.get(cand.apn), recipe, ch, client, agent))
    if not dry_run and out:
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, [
                (d["apn"], d["channel"], d["status"], d["content"], Jsonb(d["source_facts"]), d["recipe"],
                 d["assigned_to"], d["mailing_address"], d["salutation"], d["template_key"], d["model_version"],
                 d["blocked_reason"], d["uses_sample_data"]) for d in out])
        conn.commit()
    return {"drafts": out, "parcels": len(cands), "written": 0 if dry_run else len(out),
            "by_recipe": Counter(d["recipe"] for d in out), "by_status": Counter(d["status"] for d in out),
            "blocked": Counter(d["blocked_reason"] or "not blocked" for d in out), "dry_run": dry_run}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.outreach")
    ap.add_argument("--client", required=True)
    ap.add_argument("--channels", default=",".join(DEFAULT_CHANNELS),
                    help="comma list of mail, email, call_task (default: mail)")
    ap.add_argument("--drafts", type=int, default=None, help="parcels to draft (default: outreach.drafts_per_run)")
    ap.add_argument("--dry-run", action="store_true", help="render and print, write nothing")
    args = ap.parse_args(argv)
    client = load_client(args.client)
    with connect() as conn:
        res = run_outreach(conn, client, channels=tuple(args.channels.split(",")), drafts=args.drafts,
                           dry_run=args.dry_run)
    print(f"{'DRY RUN: ' if res['dry_run'] else ''}{res['parcels']} parcels, {len(res['drafts'])} drafts "
          f"({res['written']} written); by recipe {dict(res['by_recipe'])}; status {dict(res['by_status'])}; "
          f"blocked {dict(res['blocked'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
