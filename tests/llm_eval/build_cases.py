"""One-off generator for tests/llm_eval/lead_brief.json: freezes real packets (addresses anonymized) from the local DB,
then appends hand-built cases that tempt the three failure modes lead_brief v2 forbids (restating the page header, a
jargon headline, a generic "market update" angle). Packets use the v2 shape (signal meanings and recipe rationales).
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
        # v2: a brief must ground itself in at least one of the home's own signal records (it may pick the angle)
        top = [r["id"] for r in pk.packet["records"] if r["kind"] == "signal"]
        out.append({"id": f"lead-{len(out) + 1}", "address": "100 Example St", "packet": pk.packet,
                    "must_cite_any": top or [pk.packet["records"][1]["id"]],
                    "forbidden": [r"tax", r"default", r"financ", r"struggl", r"elderly", r"\bneeds? money"]})
        if len(out) == 10:
            break


def comp(key, kind="signal", points=10.0, group=None, facts=None, sample=False, estimate=False, **kw):
    c = {"key": key, "kind": kind, "contribution": points, "facts": facts or {}, "is_sample": sample, "is_estimate": estimate,
         "group": group, "family": "permits", "signal_id": f"sig-{len(out)}-{key}", "source_key": "dev_permits",
         "signal_date": "2026-09-14", "confidence": 0.95}
    c.update(kw)
    return c


def owner(key, facts, points=10.0, **kw):
    return comp(key, kind="owner", points=points, facts=facts, sample=True, provider="sample", as_of="2026-11-18", **kw)


def permit(label, date, group, n=1):
    return comp(f"permit_approved:{group}", group=group, signal_date=date,
                facts={"group": group, "issue_date": date, "permit_count": n, "permit_label": label})


def synthetic(case_id, parcel, components, recipes, **checks):
    pk = build_packet({"apn": "1", "situs_address": "100 Example St", **parcel}, {"id": "S", "components": components,
                      "recipe_matches": recipes}, labels, cfg)
    sigs = [r["id"] for r in pk.packet["records"] if r["kind"] == "signal"]
    out.append({"id": case_id, "address": "100 Example St", "packet": pk.packet, "must_cite_any": sigs,
                "forbidden": [r"tax", r"default", r"financ", r"struggl", r"elderly", r"\bneeds? money", r"sample data", r"playbook", r"recipe"],
                **checks})


# restating bait: a lot size, zoning, permit date and long ownership are all there to be repeated
synthetic("lead-11", {"neighborhood": "La Jolla", "zoning": "RS-1-2", "lot_sqft": 13000.0, "year_built": 1962},
          [permit("Plumbing work", "2026-09-14", "pre_sale_prep"),
           owner("owner:years_owned", {"years_owned": 31}, 15), owner("owner:mortgage_open_false", {})],
          ["pre_list_prep", "downsizer"],
          max_header_facts=1)
# jargon headline bait: zoning code, SB 9 and lot size invite "RM-2-5 lot with SB 9 potential"
synthetic("lead-12", {"neighborhood": "Pacific Beach", "zoning": "RM-2-5", "lot_sqft": 9800.0, "year_built": 1955},
          [comp("sb9_lot_split_estimate", group="upzoning", estimate=True, signal_date="2026-11-18", points=8, confidence=0.5),
           owner("owner:years_owned", {"years_owned": 26}, 15), owner("owner:absentee", {})],
          ["builder_bait"], forbidden_headline=[r"SB ?\d", r"RM-", r"zon", r"sq\.? ?ft", r"upzon", r"^\W*recent"])
# generic-angle bait: remodel permits on a home with a rental license
synthetic("lead-13", {"neighborhood": "Pacific Beach", "zoning": "RS-1-7", "lot_sqft": 6700.0, "year_built": 1948},
          [permit("Building permit (remodel, addition or new construction)", "2026-08-20", "remodel_addition", 2),
           comp("stro_license_active", group="stro", signal_date="2026-11-18", points=5, facts={"tier": "Tier 3"}),
           owner("owner:years_owned", {"years_owned": 24}, 10)],
          ["downsizer"], forbidden_angle=[r"market (update|report|overview)", r"inventory", r"recent (sales|activity)", r"neighbou?rhood (update|overview)"])
# restating bait: a stalled project with lot, zoning and dates in view
synthetic("lead-14", {"neighborhood": "Mission Beach", "zoning": "RM-3-7", "lot_sqft": 2750.0, "year_built": 1972},
          [comp("permit_stalled", group="permits", points=15, facts={"group": "remodel_addition", "expire_date": "2026-02-10", "permit_count": 1,
                                                                    "permit_label": "Building permit (remodel, addition or new construction)"}),
           owner("owner:absentee", {}), owner("owner:years_owned", {"years_owned": 22}, 10)],
          ["tired_landlord", "stalled_project"],
          max_header_facts=1)
# "Recent permits" headline bait plus market-update angle bait
synthetic("lead-15", {"neighborhood": "La Jolla", "zoning": "RS-1-5", "lot_sqft": 7500.0, "year_built": 1966},
          [permit("Building permit (remodel, addition or new construction)", "2026-11-10", "remodel_addition", 2),
           permit("Heating, cooling or mechanical work", "2026-11-10", "pre_sale_prep"),
           owner("owner:years_owned", {"years_owned": 21}, 10), owner("owner:mortgage_open_false", {})],
          ["pre_list_prep", "downsizer"], forbidden_headline=[r"^\W*recent", r"RS-", r"zon"],
          forbidden_angle=[r"market (update|report|overview)", r"inventory", r"recent (sales|activity)"])

Path(__file__).with_name("lead_brief.json").write_text(json.dumps(out, indent=1))
print(len(out), "cases")
