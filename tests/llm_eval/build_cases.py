"""One-off generator for tests/llm_eval/lead_brief.json: freezes real packets (addresses anonymized) from the local DB.
Run from the repo root:  PYTHONPATH=pipelines python tests/llm_eval/build_cases.py"""
import json
from pathlib import Path

from territory.db import connect
from territory.llm.tasks.lead_brief import build_packet, select_parcels
from territory.scoring_engine import load_scoring_config

cfg = load_scoring_config()
labels = {k: v.get("label", k) for k, v in cfg["recipes"].items()}
out, seen = [], set()
with connect() as conn:
    rows = select_parcels(conn, top=400)
    # spread across the score range, skipping near-duplicates of the same record pattern
    step = max(1, len(rows) // 40)
    for (apn, sid, score, comps, recipes, situs, hood, zoning, lot, yb) in rows[::step]:
        parcel = {"apn": apn, "situs_address": "100 Example St", "neighborhood": hood, "zoning": zoning,
                  "lot_sqft": float(lot) if lot else None, "year_built": yb}
        pk = build_packet(parcel, {"id": "S", "components": comps, "recipe_matches": recipes}, labels, cfg)
        if pk is None:
            continue
        pattern = tuple(sorted(r["text"][:18] for r in pk.packet["records"]))
        if pattern in seen:
            continue
        seen.add(pattern)
        top = [r["id"] for r in pk.packet["records"] if r["kind"] == "signal"][:1]
        out.append({"id": f"lead-{len(out) + 1}", "address": "100 Example St", "packet": pk.packet,
                    "must_cite_any": top or [pk.packet["records"][1]["id"]],
                    "forbidden": [r"tax", r"default", r"financ", r"struggl", r"elderly", r"\bneeds? money"]})
        if len(out) == 10:
            break
Path(__file__).with_name("lead_brief.json").write_text(json.dumps(out, indent=1))
print(len(out), "cases")
