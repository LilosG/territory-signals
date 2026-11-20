"""Eval: python -m territory.llm.eval --provider <p> --model <m> [--base-url <u>] [--tasks ...]

Runs the fixed cases in tests/llm_eval/ against a provider and prints the pass rate per task and the total cost.
A new provider or model must score >= 90% before a client config switches to it (DEPLOY.md). No database needed."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from territory.llm.base import Provider
from territory.llm.prompts import load_prompt
from territory.llm.validators import header_facts_in
from territory.scoring_engine import load_scoring_config
from territory.llm.tasks import lead_brief, permit_intent, weekly_brief

CASES_DIR = Path(__file__).resolve().parents[3] / "tests" / "llm_eval"
PASS_MARK = 0.90


def load_cases(name: str) -> list[dict]:
    return json.loads((CASES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def make_provider(provider: str, model: str, base_url: str | None, api_key_env: str = "LLM_API_KEY") -> Provider:
    key = os.environ.get(api_key_env, "")
    if provider == "openai_compatible":
        from territory.llm.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(base_url or "https://openrouter.ai/api/v1", key, model)
    if provider == "anthropic":
        from territory.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(key, model)
    raise SystemExit(f"unknown provider {provider!r}")


class Acc:
    def __init__(self) -> None:
        self.cost: float | None = 0.0
        self.unknown = False

    def add(self, c: float | None) -> None:
        if c is None:
            self.unknown = True
        elif self.cost is not None:
            self.cost += c


def eval_permit_intent(provider: Provider, model: str, acc: Acc, cases: list[dict] | None = None) -> dict:
    cases = cases or load_cases("permit_intent")
    system, _ = load_prompt("permit_intent")
    results = []
    bs = permit_intent.BATCH
    chunks = [cases[i:i + bs] for i in range(0, len(cases), bs)]

    def one(chunk):
        permits = [permit_intent.Permit(c["id"], c["description"], c.get("permit_type", "")) for c in chunk]
        return chunk, permit_intent.classify_batch(provider, system, permits, model)    # retry once, no fallback

    with ThreadPoolExecutor(4) as ex:
        for chunk, res in ex.map(one, chunks):
            for call in res.calls:
                acc.add(call.cost_usd)
            for c, last in zip(chunk, res.final):
                status, out, why = last.status, last.output, last.reason
                ok, note = status == "valid", why
                if ok and out["intent"] not in c["ok"]:
                    ok, note = False, f"intent {out['intent']} not in {c['ok']}"
                if ok and not set(c.get("tags", [])) <= set(out["scope_tags"]):
                    ok, note = False, f"missing tags {sorted(set(c['tags']) - set(out['scope_tags']))}"
                results.append({"id": c["id"], "pass": ok, "note": note})
    return {"results": results}


def _forbidden(patterns: list[str], texts: list[str]) -> str | None:
    for p in patterns:
        for t in texts:
            if re.search(p, t, re.I):
                return f"forbidden content {p!r}"
    return None


NAMES = tuple(v.get("label", k) for k, v in load_scoring_config()["recipes"].items())


def eval_lead_brief(provider: Provider, model: str, acc: Acc, cases: list[dict] | None = None) -> dict:
    cases = cases or load_cases("lead_brief")
    system, _ = load_prompt("lead_brief")

    def one(c):
        real = {r["id"]: r["id"] for r in c["packet"]["records"]}       # eval ids stay as R-ids
        pk = lead_brief.Packet("EVAL", c["address"], c["packet"], real, {r["id"]: bool(r["is_sample"]) for r in c["packet"]["records"]},
                               NAMES)
        return c, lead_brief.brief_one(provider, system, pk, model)       # retry once, no fallback

    results = []
    with ThreadPoolExecutor(4) as ex:
        for c, chain in ex.map(one, cases):
            for a in chain:
                acc.add(a.cost_usd)
            last = chain[-1]
            status, out, cited = last.status, last.output, last.cited
            ok, note = status == "valid", "; ".join(last.problems)[:200]
            if ok and not set(c["must_cite_any"]) & set(cited):
                ok, note = False, f"cites none of {c['must_cite_any']}"
            if ok:
                texts = [out["headline"], out["summary"], out["suggested_angle"], *[x["text"] for x in out["claims"]]]
                bad = (_forbidden(c["forbidden"], texts) or _forbidden(c.get("forbidden_headline", []), [out["headline"]])
                       or _forbidden(c.get("forbidden_summary", []), [out["summary"]])
                       or _forbidden(c.get("forbidden_angle", []), [out["suggested_angle"]]))
                if bad:
                    ok, note = False, bad
                elif len(header_facts_in(out["summary"])) > c.get("max_header_facts", 1):
                    ok, note = False, "summary restates the page header"
            results.append({"id": c["id"], "pass": ok, "note": note})
    return {"results": results}


def eval_weekly_brief(provider: Provider, model: str, acc: Acc, cases: list[dict] | None = None) -> dict:
    from territory.llm import attempts as at
    cases = cases or load_cases("weekly_brief")
    system, _ = load_prompt("weekly_brief")

    def one(c):
        def check(v):
            problems = weekly_brief.validate(v, c["facts"])
            covered = {s.neighborhood for s in v.sections}
            if not problems and covered != set(c["facts"]["neighborhoods"]):
                problems = [f"sections cover {sorted(covered)}"]
            if not problems:
                bad = _forbidden([re.escape(x) for x in c["forbidden_in_newsletter"]], [v.newsletter_paragraph])
                problems = [bad] if bad else []
            return at.Evaluation(v.model_dump() if not problems else None, problems)
        return c, at.run_chain(provider, "weekly_brief", system, json.dumps(weekly_brief.model_view(c["facts"]), ensure_ascii=False, indent=1),
                               weekly_brief.WeeklyOut, check, model)               # retry once, no fallback

    results = []
    with ThreadPoolExecutor(3) as ex:
        for c, chain in ex.map(one, cases):
            for a in chain:
                acc.add(a.cost_usd)
            last = chain[-1]
            results.append({"id": c["id"], "pass": last.status == "valid", "note": (last.reason or "")[:200],
                            "first_try": chain[0].status == "valid"})
    return {"results": results}


EVALS = {"permit_intent": eval_permit_intent, "lead_brief": eval_lead_brief, "weekly_brief": eval_weekly_brief}


def run_eval(provider: Provider, model: str, tasks: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"model": model, "tasks": {}}
    total = Acc()
    for t in tasks or list(EVALS):
        acc = Acc()
        r = EVALS[t](provider, model, acc)
        n = len(r["results"])
        passed = sum(1 for x in r["results"] if x["pass"])
        out["tasks"][t] = {"pass": passed, "n": n, "rate": passed / n if n else 0.0, "cost_usd": acc.cost,
                           "cost_unknown": acc.unknown, "failures": [x for x in r["results"] if not x["pass"]]}
        total.add(acc.cost)
        if acc.unknown:
            total.unknown = True
    out["total_cost_usd"] = total.cost
    out["cost_unknown"] = total.unknown
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.llm.eval")
    ap.add_argument("--provider", required=True, choices=["openai_compatible", "anthropic"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url")
    ap.add_argument("--api-key-env", default="LLM_API_KEY")
    ap.add_argument("--tasks", default=",".join(EVALS))
    ap.add_argument("--json", help="write the full result to this file")
    ap.add_argument("-v", "--verbose", action="store_true", help="print each failure")
    a = ap.parse_args(argv)
    res = run_eval(make_provider(a.provider, a.model, a.base_url, a.api_key_env), a.model, a.tasks.split(","))
    for t, r in res["tasks"].items():
        print(f"{t:15s} {r['pass']:3d}/{r['n']:<3d} {r['rate']:.0%}" + ("   PASS" if r["rate"] >= PASS_MARK else "   below 90%"))
        if a.verbose:
            for f in r["failures"]:
                print(f"    {f['id']}: {f['note']}")
    cost = "unknown (no price on file)" if res["cost_unknown"] and not res["total_cost_usd"] else f"${res['total_cost_usd']:.4f}"
    print(f"total cost: {cost}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
