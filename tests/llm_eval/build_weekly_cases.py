"""Three fixed weekly fact packets: a busy week, a quiet week with no baseline, and a week with tax-default counts."""
import json
from pathlib import Path

HOODS = ["La Jolla", "Mission Beach", "Pacific Beach"]


def scope(strong, new, recipes, permits, tax_new, tax_total, strs, movers):
    return {"strong_leads_now": strong, "new_strong_leads": new, "recipe_counts": recipes,
            "new_pre_sale_permits": permits, "tax_default_new_this_week": tax_new, "tax_default_total": tax_total,
            "new_str_removals": strs, "top_movers": movers}


def mv(addr, hood, a, b):
    return {"address": addr, "neighborhood": hood, "score_before": a, "score_now": b, "change": b - a}


busy_m = [mv("100 Example St", "La Jolla", 52, 66), mv("200 Sample Ave", "Pacific Beach", 41, 55),
          mv("300 Test Ct", "La Jolla", 60, 49), mv("400 Demo Way", "Mission Beach", 38, 47),
          mv("500 Mock Blvd", "Pacific Beach", 63, 55)]
cases = [
    {"id": "weekly-busy", "facts": {
        "week": {"start": "2026-11-09", "end": "2026-11-16"}, "baseline": {"kind": "week_start", "compared_with": "2026-11-09"},
        "territory": scope(14, 5, {"Pre-list prep": {"now": 40, "before": 34, "change": 6}, "Builder bait": {"now": 22, "before": 22, "change": 0}}, 31, 2, 39, 3, busy_m),
        "neighborhoods": {"La Jolla": scope(7, 3, {"Pre-list prep": {"now": 18, "before": 15, "change": 3}}, 14, 1, 20, 1, [busy_m[0], busy_m[2]]),
                          "Mission Beach": scope(1, 0, {"Pre-list prep": {"now": 4, "before": 4, "change": 0}}, 3, 0, 2, 0, [busy_m[3]]),
                          "Pacific Beach": scope(6, 2, {"Pre-list prep": {"now": 18, "before": 15, "change": 3}}, 14, 1, 17, 2, [busy_m[1], busy_m[4]])}}},
    {"id": "weekly-quiet", "facts": {
        "week": {"start": "2026-11-09", "end": "2026-11-16"}, "baseline": {"kind": "none", "compared_with": None},
        "territory": scope(2, None, {}, 0, 0, 0, 0, []),
        "neighborhoods": {h: scope(0, None, {}, 0, 0, 0, 0, []) for h in HOODS}}},
    {"id": "weekly-tax", "facts": {
        "week": {"start": "2026-11-02", "end": "2026-11-09"}, "baseline": {"kind": "earliest_available", "compared_with": "2026-11-03"},
        "territory": scope(9, 4, {"Short-term rental exit": {"now": 3, "before": 1, "change": 2}}, 12, 6, 45, 2, busy_m[:3]),
        "neighborhoods": {"La Jolla": scope(4, 2, {"Short-term rental exit": {"now": 1, "before": 0, "change": 1}}, 5, 3, 22, 1, [busy_m[0], busy_m[2]]),
                          "Mission Beach": scope(0, 0, {}, 1, 0, 3, 0, []),
                          "Pacific Beach": scope(5, 2, {"Short-term rental exit": {"now": 2, "before": 1, "change": 1}}, 6, 3, 20, 1, [busy_m[1]])}}},
]
for c in cases:
    c["forbidden_in_newsletter"] = [m["address"] for m in c["facts"]["territory"]["top_movers"]] + ["tax", "default"]
Path(__file__).with_name("weekly_brief.json").write_text(json.dumps(cases, indent=1))
print(len(cases), "cases")
