"""lead_brief: a short internal brief per parcel, written from a facts packet built from the database only."""
from __future__ import annotations

import json
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from territory.config import ClientConfig
from territory.llm import attempts as at, store
from territory.llm.base import Provider
from territory.llm.prompts import load_prompt
from territory.llm.validators import (
    check_addresses, check_angle, check_banned_words, check_headline, check_header_facts, check_intent_and_meta,
    check_numbers, check_speculation, strings_of,
)
from territory.scoring_engine import load_scoring_config, phrase

TASK = "lead_brief"
SENSITIVE_KEYS = ("tax_default", "owner:ownership_transfer")
SENSITIVE_RECIPES = {"financial_pressure", "quiet_inheritance"}


class Claim(BaseModel):
    text: str
    record_ids: list[str]


class LeadBriefOut(BaseModel):
    headline: str
    summary: str
    claims: list[Claim]
    suggested_angle: str


@dataclass
class Packet:
    apn: str
    address: str
    packet: dict[str, Any]              # what the model sees (records use short ids R1..Rn)
    real_ids: dict[str, str]            # R1 -> signal uuid / owner:<field> / parcel:<apn> / score:<id>
    sample: dict[str, bool]             # R1 -> is_sample
    recipe_names: tuple[str, ...] = ()  # internal category names that stay out of the headline


def _component_labels() -> dict[str, str]:
    from territory.export_catalog import load_signal_labels
    return load_signal_labels().get("components") or {}


def _cap(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


def load_meanings() -> dict[str, str]:
    from territory.export_catalog import load_signal_labels
    return load_signal_labels().get("signal_meanings") or {}


def build_packet(parcel: dict, score_row: dict, recipe_labels: dict[str, str], cfg: dict | None = None,
                 meanings: dict[str, str] | None = None) -> Packet | None:
    """Facts packet from DB rows only. Sensitive records (tax default, ownership transfer, distress recipes) are left out:
    briefs appear on lists, where those must never show (presentation rules). None when there is nothing to say.

    Phase 5G: after the property's own records come two kinds of citable explanation, both read from config and never
    written by the model: the plain meaning of each signal present (config/signal_labels.yaml `signal_meanings`) and the
    plain rationale of each matched recipe (config/scoring.yaml `rationale`). The model may explain why a signal or
    pattern matters only with that text."""
    cfg = cfg or load_scoring_config()
    meanings = load_meanings() if meanings is None else meanings
    records: list[dict] = []
    real: dict[str, str] = {}
    sample: dict[str, bool] = {}
    comp_keys: list[str] = []

    def add(real_id: str, kind: str, text: str, source: str | None, date: str | None, conf: float | None,
            is_sample: bool, is_estimate: bool) -> None:
        rid = f"R{len(records) + 1}"
        records.append({"id": rid, "kind": kind, "source": source, "date": date, "confidence": conf,
                        "is_sample": is_sample, "is_estimate": is_estimate, "text": text})
        real[rid] = real_id
        sample[rid] = is_sample

    bits = [f"in {parcel['neighborhood']}" if parcel.get("neighborhood") else None,
            f"zoned {parcel['zoning']}" if parcel.get("zoning") else None,
            f"lot {int(round(parcel['lot_sqft'])):,} sq ft" if parcel.get("lot_sqft") else None,
            f"built {parcel['year_built']}" if parcel.get("year_built") else None]
    add(f"parcel:{parcel['apn']}", "parcel", "Residential parcel " + ", ".join(b for b in bits if b), "parcels", None,
        None, False, False)
    for c in sorted(score_row["components"] or [], key=lambda c: -c["contribution"]):
        if c["contribution"] <= 0 or any(c["key"].startswith(k) for k in SENSITIVE_KEYS):
            continue
        if c.get("group") in ("distress", "life_event"):
            continue
        if c["kind"] == "signal":
            rid, source, date = c["signal_id"], c.get("source_key"), c.get("signal_date")
        else:
            rid, source, date = f"owner:{c['key'].split(':', 1)[1]}", c.get("provider"), c.get("as_of")
        f = c["facts"]
        text = _cap(phrase(c))
        if c["key"].startswith("owner:est_equity") and f.get("est_equity") is not None:
            text += f"; estimated equity about ${round(f['est_equity']):,}"
        add(rid, "owner" if c["kind"] == "owner" else "signal", text, source, date, c.get("confidence"),
            bool(c.get("is_sample")), bool(c.get("is_estimate")))
        comp_keys.append(c["key"])
    pub = [r for r in (score_row["recipe_matches"] or []) if r not in SENSITIVE_RECIPES]
    if len(records) <= 1 and not pub:
        return None
    labels = _component_labels()
    for key in dict.fromkeys(comp_keys):                       # one meaning per signal type present
        if meanings.get(key):
            add(f"meaning:{key}", "meaning", f"{labels.get(key, key)}: {meanings[key]}", "config", None, None, False, False)
    for r in pub:                                              # one rationale per matched recipe
        why = (cfg["recipes"].get(r) or {}).get("rationale")
        if why:
            add(f"recipe:{r}", "pattern", f"Pattern this home matches: {why}", "config", None, None, False, False)
    if len(records) <= 1:
        return None
    packet = {"parcel": {"neighborhood": parcel.get("neighborhood")}, "records": records}
    return Packet(parcel["apn"], parcel.get("situs_address") or "", packet, real, sample,
                  tuple(recipe_labels.get(r, r) for r in cfg["recipes"]))


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text.strip()) if s])


def validate(out: LeadBriefOut, pk: Packet) -> tuple[dict | None, list[str], list[str], bool]:
    """Returns (stored output with real record ids | None, problems, cited real ids, uses_sample)."""
    problems: list[str] = []
    if not out.headline.strip() or not out.summary.strip():
        return None, ["empty output"], [], False
    problems += check_headline(out.headline, internal_names=pk.recipe_names)
    n = sentences(out.summary)
    if not 2 <= n <= 3:
        problems.append(f"summary has {n} sentences (need 2 or 3)")
    problems += check_header_facts(out.summary)
    nwords = len(out.summary.split())
    if nwords > 80:
        problems.append(f"summary has {nwords} words (max 80)")
    if not out.claims:
        problems.append("no claims")
    cited: list[str] = []
    for i, cl in enumerate(out.claims, 1):
        if not cl.record_ids:
            problems.append(f"claim {i} cites no record")
        for rid in cl.record_ids:
            if rid not in pk.real_ids:
                problems.append(f"claim {i} cites {rid!r}, which is not in the packet")
            elif rid not in cited:
                cited.append(rid)
    if cited and all(pk.real_ids[r].startswith(("meaning:", "recipe:")) for r in cited):
        problems.append("claims cite only explanations; cite at least one record about this home itself")
    texts = [out.headline, out.summary, out.suggested_angle, *[c.text for c in out.claims]]
    problems += check_banned_words(texts)
    problems += check_intent_and_meta([out.headline, out.summary, *[c.text for c in out.claims]])
    problems += check_angle(out.suggested_angle)
    problems += check_numbers(texts, pk.packet)
    problems += check_addresses(texts, [pk.address])
    problems += check_speculation(texts, pk.packet)
    if problems:
        return None, problems, [], False
    stored = {"headline": out.headline.strip(), "summary": out.summary.strip(),
              "claims": [{"text": c.text.strip(), "record_ids": [pk.real_ids[r] for r in c.record_ids]} for c in out.claims],
              "suggested_angle": out.suggested_angle.strip()}
    return stored, [], [pk.real_ids[r] for r in cited], any(pk.sample[r] for r in cited)


def packet_prompt(pk: Packet) -> str:
    return json.dumps(pk.packet, ensure_ascii=False, indent=1)


def evaluate(out: LeadBriefOut, pk: Packet) -> at.Evaluation:
    stored, problems, cited, uses_sample = validate(out, pk)
    return at.Evaluation(stored, problems, cited, uses_sample)


def brief_one(provider: Provider, system: str, pk: Packet, model: str | None,
              fallback_model: str | None = None) -> list[at.Attempt]:
    """One brief: primary, then a retry with the rejection reason appended, then the fallback model (attempts.py)."""
    return at.run_chain(provider, TASK, system, packet_prompt(pk), LeadBriefOut, lambda v: evaluate(v, pk), model,
                        fallback_model)


def select_parcels(conn, top: int = 200, min_score: int = 40, limit: int | None = None) -> list[tuple]:
    """Score >= min_score, plus the top `top` by score (union), best first. `limit` keeps only the best N."""
    rows = conn.execute(
        """with s as (select * from latest_scores),
                top as (select apn from s order by score desc, apn limit %s)
           select s.apn, s.id, s.score, s.components, s.recipe_matches, p.situs_address,
                  coalesce(p.neighborhood, p.planning_area), p.zoning, p.lot_sqft, p.year_built
             from s join parcels p on p.apn = s.apn
            where s.score >= %s or s.apn in (select apn from top)
            order by s.score desc, s.apn""", (top, min_score)).fetchall()
    return rows[:limit] if limit else rows


def run(conn, client: ClientConfig, provider: Provider, stats: store.TaskStats, limit: int | None = None,
        workers: int = 6) -> None:
    """Briefs for the selected parcels. Provider calls run on `workers` threads; every database read and write stays on this
    thread. Cached parcels (same facts and prompt version) cost nothing."""
    system, version = load_prompt(TASK)
    model = client.llm.model_for(TASK)
    fallback = client.llm.fallback_model_for(TASK)
    stats.model = model
    cfg = load_scoring_config()
    labels = {k: v.get("label", k) for k, v in cfg["recipes"].items()}
    meanings = load_meanings()
    guard = store.BudgetGuard(conn, client.client_id, client.llm.monthly_budget_usd, stats)
    todo: list[tuple[str, Packet, str]] = []
    for (apn, sid, score, comps, recipes, situs, hood, zoning, lot, yb) in select_parcels(conn, limit=limit):
        parcel = {"apn": apn, "situs_address": situs, "neighborhood": hood, "zoning": zoning,
                  "lot_sqft": float(lot) if lot is not None else None, "year_built": yb}
        pk = build_packet(parcel, {"id": sid, "components": comps, "recipe_matches": recipes}, labels, cfg, meanings)
        if pk is None:
            continue
        ihash = store.input_hash({"packet": pk.packet, "real": pk.real_ids, "prompt": store.text_hash(system)})
        if store.find_cached(conn, client.client_id, TASK, apn, ihash, version):
            stats.cached += 1
            continue
        todo.append((apn, pk, ihash))

    pending: dict = {}
    queue = iter(todo)

    def submit(ex) -> bool:
        if not guard.allow():
            return False
        item = next(queue, None)
        if item is None:
            return False
        pending[ex.submit(brief_one, provider, system, item[1], model, fallback)] = item
        return True

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in range(workers):
            if not submit(ex):
                break
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for f in finished:
                apn, pk, ihash = pending.pop(f)
                chain = f.result()
                at.record(stats, chain, f"parcel {apn}")
                store.insert_outputs(conn, at.rows(chain, client.client_id, TASK, "parcel", apn, ihash, version))
                submit(ex)
