"""Side-by-side writing samples: the same 3 top-lead briefs and 1 weekly brief from each model, from the local database.

    python -m territory.llm.compare --models a,b,c --out /tmp/compare.json

Nothing is stored in ai_outputs; this is for choosing a model (docs/reports/model-selection.md)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from territory.db import connect
from territory.llm import attempts as at
from territory.llm.eval import make_provider
from territory.llm.prompts import load_prompt
from territory.llm.tasks import lead_brief, weekly_brief
from territory.scoring_engine import load_scoring_config


def samples(models: list[str], n_leads: int = 3) -> dict:
    cfg = load_scoring_config()
    labels = {k: v.get("label", k) for k, v in cfg["recipes"].items()}
    with connect() as conn:
        packets = []
        for (apn, sid, score, comps, recipes, situs, hood, zoning, lot, yb) in lead_brief.select_parcels(conn, limit=40):
            parcel = {"apn": apn, "situs_address": situs, "neighborhood": hood, "zoning": zoning,
                      "lot_sqft": float(lot) if lot is not None else None, "year_built": yb}
            pk = lead_brief.build_packet(parcel, {"id": sid, "components": comps, "recipe_matches": recipes}, labels, cfg)
            if pk:
                packets.append((apn, score, pk))
            if len(packets) == n_leads:
                break
        facts = weekly_brief.compute_facts(conn, date.today(), cfg)
    out: dict = {"leads": [{"apn": a, "score": s, "address": p.address, "records": p.packet["records"]} for a, s, p in packets],
                 "weekly_facts": facts, "models": {}}
    lsys, _ = load_prompt("lead_brief")
    wsys, _ = load_prompt("weekly_brief")
    for m in models:
        prov = make_provider("openai_compatible", m, "https://openrouter.ai/api/v1")
        r: dict = {"leads": [], "weekly": None, "cost_leads": 0.0, "cost_weekly": 0.0}
        for apn, score, pk in packets:
            chain = lead_brief.brief_one(prov, lsys, pk, m)
            last = chain[-1]
            tin, tout, cost = at.totals(chain)
            r["leads"].append({"apn": apn, "status": last.status, "output": last.output, "problems": last.problems,
                               "cost": cost, "tokens": tin + tout})
            r["cost_leads"] += cost or 0
        chain = at.run_chain(prov, "weekly_brief", wsys, json.dumps(facts, ensure_ascii=False, indent=1), weekly_brief.WeeklyOut,
                             lambda v: weekly_brief.evaluate(v, facts), m)
        last = chain[-1]
        tin, tout, cost = at.totals(chain)
        r["weekly"] = {"status": last.status, "problems": last.problems, "output": last.output, "cost": cost, "tokens": tin + tout}
        r["cost_weekly"] = cost or 0
        out["models"][m] = r
        print(m, [x["status"] for x in r["leads"]], r["weekly"]["status"], flush=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.llm.compare")
    ap.add_argument("--models", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = samples(a.models.split(","))
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
