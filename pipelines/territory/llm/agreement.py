"""Shadow-mode report: how often the AI's permit intent agrees with the group the permit map assigns.

    python -m territory.llm.agreement --client kaiser-team [--out docs/reports/permit-intent-agreement.md]

The permit groups (config/permit_signal_map.yaml) are not intents, so agreement needs a stated reading of each group:
IMPLIED_INTENT below. The 'other' group has no implied intent; it is reported as a distribution only."""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from territory.config import load_client
from territory.db import connect
from territory.llm.tasks.permit_intent import INTENTS

IMPLIED_INTENT = {
    "pre_sale_prep": "prep_to_sell",
    "remodel_addition": "long_term_stay",
    "adu": "investment_or_redevelopment",
    "demolition_lot_split": "investment_or_redevelopment",
    "solar_energy": "long_term_stay",
}
GROUPS = ["pre_sale_prep", "remodel_addition", "adu", "demolition_lot_split", "solar_energy", "other"]
DEFAULT_OUT = Path(__file__).resolve().parents[3] / "docs" / "reports" / "permit-intent-agreement.md"

QUERY = """
select distinct on (s.source_record_id) s.source_record_id, s.signal_group,
       coalesce(nullif(btrim(s.details->>'scope'), ''), nullif(btrim(s.details->>'job_description'), '')) as descr,
       a.output->>'intent', a.output->>'confidence'
  from signals s
  join latest_ai_outputs a on a.task = 'permit_intent' and a.client_id = %s and a.subject_id = s.source_record_id
 where s.signal_type = 'permit_approved' and s.superseded_by is null
 order by s.source_record_id, s.signal_date desc nulls last
"""


def build(rows: list[tuple], sample_n: int = 20) -> dict:
    by_group: dict[str, Counter] = defaultdict(Counter)
    disagreements = []
    for rid, group, descr, intent, _conf in rows:
        by_group[group][intent] += 1
        want = IMPLIED_INTENT.get(group)
        if want and intent != want:
            disagreements.append((rid, group, descr, intent))
    disagreements.sort(key=lambda r: __import__("hashlib").md5(r[0].encode()).hexdigest())   # stable pseudo-random sample
    return {"by_group": by_group, "disagreements": disagreements, "sample": disagreements[:sample_n]}


def render(rows: list[tuple], model_note: str, cost_note: str) -> str:
    r = build(rows)
    out = ["# Permit intent: AI vs permit group (shadow mode)", "",
           f"{len(rows):,} permits with an AI intent. {model_note} {cost_note}", "",
           "The AI intent is stored and shown nowhere; it does not change scores or recipes. "
           "Agreement compares it with the group `config/permit_signal_map.yaml` assigns, read as follows "
           "(the groups are not intents, so this reading is the assumption being tested):", ""]
    out += [f"- `{g}` implies `{i}`" for g, i in IMPLIED_INTENT.items()] + ["- `other` has no implied intent (distribution only)", ""]
    out += ["## Agreement per group", "", "| Group | Permits | Agree | Agreement | Most common AI intent |", "|---|---|---|---|---|"]
    tot_n = tot_ok = 0
    for g in GROUPS:
        c = r["by_group"].get(g)
        if not c:
            continue
        n = sum(c.values())
        want = IMPLIED_INTENT.get(g)
        ok = c[want] if want else None
        if want:
            tot_n += n
            tot_ok += ok
        top, topn = c.most_common(1)[0]
        out.append(f"| {g} | {n:,} | {ok if ok is not None else 'n/a':,} | " + (f"{ok / n:.1%}" if want else "n/a") + f" | {top} ({topn / n:.0%}) |"
                   if want else f"| {g} | {n:,} | n/a | n/a | {top} ({topn / n:.0%}) |")
    out += ["", f"**Overall (groups with an implied intent): {tot_ok:,} of {tot_n:,} = {tot_ok / tot_n:.1%}.**" if tot_n else "", ""]
    out += ["## Group by AI intent (permit counts)", "", "| Group | " + " | ".join(INTENTS) + " |", "|---|" + "---|" * len(INTENTS)]
    for g in GROUPS:
        c = r["by_group"].get(g)
        if c:
            out.append(f"| {g} | " + " | ".join(f"{c[i]:,}" for i in INTENTS) + " |")
    out += ["", f"## {len(r['sample'])} sample disagreements ({len(r['disagreements']):,} in total)", "",
            "| Description | Group | AI intent |", "|---|---|---|"]
    for rid, group, descr, intent in r["sample"]:
        d = " ".join((descr or "").split())[:180].replace("|", "/")
        out.append(f"| {d} | {group} | {intent} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="territory.llm.agreement")
    ap.add_argument("--client", required=True)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)
    client = load_client(a.client)
    with connect() as conn:
        rows = conn.execute(QUERY, (client.client_id,)).fetchall()
        spent = conn.execute("select coalesce(sum(cost_usd),0), count(*) filter (where cost_usd is null), max(model) "
                             "from ai_outputs where client_id=%s and task='permit_intent'", (client.client_id,)).fetchone()
    if not rows:
        print("no permit_intent rows yet; run: python -m territory.run --client <id> --only-ai", file=sys.stderr)
        return 1
    note = f"Model `{spent[2]}`."
    cost = f"Cost of all permit_intent calls on record: ${float(spent[0]):.2f}" + (" (some calls had unknown cost)." if spent[1] else ".")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(render(rows, note, cost), encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
