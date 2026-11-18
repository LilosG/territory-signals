"""Pure scoring tests: decay, stacking, snapshot rule, recipes, reason text, determinism."""
import json
import random
import re
from datetime import date, timedelta

import pytest

from territory.scoring_engine import (
    Owner, Sig, compute_score, decay_factor, effective_signals, latest_snapshot_dates, load_scoring_config,
    match_recipes, owner_components, percentile, reason_text, round_half_up, score_parcel, signal_components,
    stacking_multiplier,
)

CFG = load_scoring_config()
AS_OF = date(2026, 11, 18)
_n = 0


def sig(type_, days_ago=10, group="other", details=None, sample=False, estimate=False, on=None):
    global _n
    _n += 1
    d = on if on is not None else AS_OF - timedelta(days=days_ago)
    return Sig(f"sig-{_n}", type_, group, d, "test", f"rec-{_n}", 0.9, "apn", estimate, sample, details or {})


def owner(**kw):
    base = dict(last_sale_date=date(1990, 1, 1), owner_occupied=True, absentee=False, out_of_state=False,
                mortgage_open=True, est_equity=1.0, is_sample=True, provider="sample", as_of=AS_OF)
    base.update(kw)
    return Owner(**base)


def score(signals=(), own=None, snap=None, cutoff=None, data=()):
    snap = snap if snap is not None else latest_snapshot_dates(list(signals), CFG)
    return score_parcel(list(signals), own, CFG, AS_OF, snap, cutoff, data)


# ---- config ------------------------------------------------------------------------------
def test_config_matches_the_spec():
    assert CFG["model_version"] == "v0.1-handset"
    s = CFG["signals"]
    assert (s["tax_default"]["weight"], s["tax_default"]["half_life_days"]) == (30, 365)
    assert (s["stro_license_removed"]["weight"], s["stro_license_removed"]["half_life_days"]) == (25, 90)
    assert s["stro_license_active"]["weight"] == 5 and s["stro_license_active"]["half_life_days"] is None
    g = s["permit_approved"]["by_group"]
    assert {k: (v["weight"], v["half_life_days"]) for k, v in g.items()} == {
        "pre_sale_prep": (20, 120), "demolition_lot_split": (15, 180), "adu": (10, 180),
        "remodel_addition": (8, 180), "solar_energy": (3, 180), "other": (0, 180)}
    assert (s["permit_stalled"]["weight"], s["permit_stalled"]["half_life_days"]) == (15, 365)
    assert s["sb79_transit_estimate"]["values"]["within_quarter_mile"] == 14
    assert s["sb79_transit_estimate"]["values"]["within_half_mile"] == 10
    assert s["sb9_lot_split_estimate"]["weight"] == 8
    assert s["fire_hazard_zone"]["values"] == {"very high": 10, "high": 6, "moderate": 3}
    assert set(CFG["recipes"]) == {"str_exit", "tired_landlord", "builder_bait", "pre_list_prep",
                                   "stalled_project", "downsizer", "insurance_squeeze",
                                   "financial_pressure", "quiet_inheritance"}
    q = CFG["recipes"]["quiet_inheritance"]
    assert q["active"] is False and q["note"] == "requires ATTOM recorder data (Phase 6)"


# ---- decay ---------------------------------------------------------------------------------
def test_decay_math():
    assert decay_factor(0, 365) == 1.0
    assert decay_factor(365, 365) == pytest.approx(0.5)
    assert decay_factor(730, 365) == pytest.approx(0.25)
    assert decay_factor(90, 90) == pytest.approx(0.5)
    assert decay_factor(10_000, None) == 1.0            # static
    assert decay_factor(-5, 120) == 1.0                  # future-dated: no decay


def test_component_contribution_uses_weight_and_half_life():
    c = signal_components([sig("tax_default", 365)], CFG, AS_OF)[0]
    assert c["raw_weight"] == 30 and c["decay_factor"] == pytest.approx(0.5)
    assert c["contribution"] == pytest.approx(15.0)
    p = signal_components([sig("permit_approved", 120, "pre_sale_prep")], CFG, AS_OF)[0]
    assert p["contribution"] == pytest.approx(10.0)
    removed = signal_components([sig("stro_license_removed", 180)], CFG, AS_OF)[0]
    assert removed["contribution"] == pytest.approx(25 * 0.25)


def test_component_carries_required_fields():
    c = signal_components([sig("sb9_lot_split_estimate", estimate=True, sample=False)], CFG, AS_OF)[0]
    for k in ("signal_id", "raw_weight", "decay_factor", "contribution", "is_sample", "is_estimate",
              "source_key", "source_record_id", "confidence", "match_method"):
        assert k in c
    assert c["is_estimate"] is True
    o = owner_components(owner(), CFG, AS_OF, None)
    assert all({"owner_field", "raw_weight", "decay_factor", "contribution", "is_sample",
                "is_estimate"} <= set(x) for x in o)


def test_permit_group_weights_and_other_scores_zero():
    comps = signal_components([sig("permit_approved", 0, g) for g in
                               ("pre_sale_prep", "demolition_lot_split", "adu", "remodel_addition",
                                "solar_energy", "other")], CFG, AS_OF)
    assert {c["group"]: c["contribution"] for c in comps} == {
        "pre_sale_prep": 20, "demolition_lot_split": 15, "adu": 10, "remodel_addition": 8, "solar_energy": 3}


def test_one_component_per_signal_key_most_recent_wins():
    comps = signal_components([sig("permit_approved", 400, "pre_sale_prep"),
                               sig("permit_approved", 5, "pre_sale_prep"),
                               sig("permit_approved", 90, "pre_sale_prep")], CFG, AS_OF)
    assert len(comps) == 1 and comps[0]["age_days"] == 5


def test_sb79_bands_and_fire_classes():
    q = signal_components([sig("sb79_transit_estimate", details={"distance_band": "within_quarter_mile"})], CFG, AS_OF)
    h = signal_components([sig("sb79_transit_estimate", details={"distance_band": "within_half_mile"})], CFG, AS_OF)
    assert q[0]["contribution"] == 14 and h[0]["contribution"] == 10
    for cls, w in (("Very High", 10), ("High", 6), ("Moderate", 3)):
        assert signal_components([sig("fire_hazard_zone", details={"hazard_class": cls})], CFG, AS_OF)[0]["contribution"] == w


# ---- owner modifiers -----------------------------------------------------------------------
def test_owner_modifiers():
    def total(**kw):
        return {c["key"]: c["contribution"] for c in owner_components(owner(**kw), CFG, AS_OF, 100.0)}
    assert total(last_sale_date=date(1996, 11, 18))["owner:years_owned"] == 15      # exactly 30 years
    assert total(last_sale_date=date(1996, 11, 19))["owner:years_owned"] == 10      # 29 years
    assert total(last_sale_date=date(2006, 11, 18))["owner:years_owned"] == 10      # exactly 20
    assert "owner:years_owned" not in total(last_sale_date=date(2006, 11, 19))      # 19 years
    assert total(absentee=True)["owner:absentee"] == 10
    assert total(out_of_state=True)["owner:out_of_state"] == 12
    assert total(mortgage_open=False)["owner:mortgage_open_false"] == 10
    assert "owner:mortgage_open_false" not in total(mortgage_open=None)
    assert total(est_equity=100.0)["owner:est_equity_top_quartile"] == 5
    assert "owner:est_equity_top_quartile" not in total(est_equity=99.9)


def test_equity_cutoff_is_the_territory_75th_percentile():
    assert percentile([1, 2, 3, 4, 5], 75) == 4
    assert percentile([], 75) is None


# ---- stacking and the cap -------------------------------------------------------------------
def test_stacking_multiplier_and_cap():
    assert [stacking_multiplier(n, CFG) for n in (0, 1)] == [1.0, 1.0]
    assert stacking_multiplier(2, CFG) == pytest.approx(1.1)
    assert stacking_multiplier(3, CFG) == pytest.approx(1.2)
    assert stacking_multiplier(4, CFG) == pytest.approx(1.3)
    assert stacking_multiplier(5, CFG) == pytest.approx(1.3)     # capped at +30%
    assert stacking_multiplier(6, CFG) == pytest.approx(1.3)


def test_score_applies_stacking_rounding_and_cap_of_100():
    # one family: no bonus
    assert score([sig("tax_default", 0)])["score"] == 30
    # two families: financial 30 + owner 10 -> 40 x 1.1 = 44
    r = score([sig("tax_default", 0)], owner(absentee=True, last_sale_date=date(2020, 1, 1), mortgage_open=True))
    assert r["families"] == ["financial", "owner"] and r["score"] == 44
    # many families, big weights: capped at 100
    sigs = [sig("tax_default", 0), sig("stro_license_removed", 0), sig("permit_approved", 0, "pre_sale_prep"),
            sig("sb79_transit_estimate", details={"distance_band": "within_quarter_mile"}),
            sig("fire_hazard_zone", details={"hazard_class": "very high"})]
    r = score(sigs, owner(absentee=True, out_of_state=True, mortgage_open=False), cutoff=0.5)
    assert len(r["families"]) == 6 and r["multiplier"] == pytest.approx(1.3)
    assert r["weighted_sum"] * 1.3 > 100 and r["score"] == 100


def test_round_half_up_not_bankers():
    assert round_half_up(2.5) == 3 and round_half_up(3.5) == 4 and round_half_up(0.49) == 0


def test_zero_weight_components_do_not_count_as_a_family():
    r = score([sig("permit_approved", 0, "other")])
    assert r["families"] == [] and r["score"] == 0


def test_score_equals_components_times_multiplier():
    r = score([sig("tax_default", 100), sig("permit_approved", 30, "adu")], owner(absentee=True))
    res = compute_score(r["components"], CFG)
    assert res["score"] == r["score"]
    assert r["weighted_sum"] == pytest.approx(sum(c["contribution"] for c in r["components"]))


# ---- snapshot rule for stro_license_active ----------------------------------------------------
def test_stro_active_counts_once_and_only_from_the_latest_snapshot():
    d1, d2, d3 = date(2026, 11, 1), date(2026, 11, 8), date(2026, 11, 15)
    repeated = [sig("stro_license_active", on=d) for d in (d1, d2, d3)]      # same license, 3 daily snapshots
    stale = [sig("stro_license_active", on=d1)]                              # dropped out of later snapshots
    other = [sig("stro_license_active", on=d3)]                              # another parcel defines the latest date
    snap = latest_snapshot_dates(repeated + stale + other, CFG)
    assert snap["stro_license_active"] == d3
    r = score(repeated, snap=snap)
    comps = [c for c in r["components"] if c["signal_type"] == "stro_license_active"]
    assert len(comps) == 1 and comps[0]["contribution"] == 5 and comps[0]["signal_date"] == str(d3)
    assert r["score"] == 5                                                   # never 15
    assert score(stale, snap=snap)["components"] == []


def test_all_snapshot_signal_types_use_the_snapshot_rule():
    old, new = date(2026, 1, 1), date(2026, 11, 1)
    sigs = [sig("sb9_lot_split_estimate", on=old), sig("sb9_lot_split_estimate", on=new),
            sig("fire_hazard_zone", on=old, details={"hazard_class": "high"})]
    snap = {"sb9_lot_split_estimate": new, "fire_hazard_zone": new}
    eff = effective_signals(sigs, CFG, snap)
    assert [s.type for s in eff] == ["sb9_lot_split_estimate"] and eff[0].date == new


def test_permit_stalled_only_counts_for_the_three_groups():
    for g, expect in (("remodel_addition", 15), ("adu", 15), ("demolition_lot_split", 15),
                      ("other", 0), ("pre_sale_prep", 0), ("solar_energy", 0)):
        r = score([sig("permit_stalled", 0, g, {"days_past_expiry": 100})])
        assert r["score"] == expect, g


# ---- recipes ---------------------------------------------------------------------------------------
def recipes(signals=(), own=None, data=()):
    snap = latest_snapshot_dates(list(signals), CFG)
    return match_recipes(effective_signals(list(signals), CFG, snap), own, CFG, AS_OF, data)


def test_str_exit():
    assert "str_exit" in recipes([sig("stro_license_removed", 30)])
    assert "str_exit" not in recipes([sig("stro_license_removed", 400)])
    assert "str_exit" not in recipes([sig("stro_license_active", 0)])


def test_tired_landlord():
    absentee = owner(absentee=True, last_sale_date=date(2005, 1, 1))
    assert "tired_landlord" in recipes([sig("tax_default", 100)], absentee)
    assert "tired_landlord" in recipes([sig("permit_stalled", 100, "adu")], absentee)
    assert "tired_landlord" not in recipes([sig("tax_default", 100)], owner(absentee=False))
    assert "tired_landlord" not in recipes([sig("tax_default", 100)], owner(absentee=True, last_sale_date=date(2020, 1, 1)))
    assert "tired_landlord" not in recipes([], absentee)


def test_builder_bait():
    up = sig("sb9_lot_split_estimate", 0)
    assert "builder_bait" in recipes([up], owner(last_sale_date=date(1999, 1, 1)))
    assert "builder_bait" in recipes([sig("sb79_transit_estimate", details={"distance_band": "within_half_mile"})],
                                     owner(absentee=True, last_sale_date=date(2024, 1, 1)))
    assert "builder_bait" not in recipes([up], owner(last_sale_date=date(2020, 1, 1)))
    assert "builder_bait" not in recipes([], owner(last_sale_date=date(1999, 1, 1)))


def test_pre_list_prep():
    p = sig("permit_approved", 60, "pre_sale_prep")
    assert "pre_list_prep" in recipes([p], owner(last_sale_date=date(2010, 1, 1)))
    assert "pre_list_prep" not in recipes([sig("permit_approved", 300, "pre_sale_prep")], owner(last_sale_date=date(2010, 1, 1)))
    assert "pre_list_prep" not in recipes([sig("permit_approved", 60, "remodel_addition")], owner(last_sale_date=date(2010, 1, 1)))
    assert "pre_list_prep" not in recipes([p], owner(last_sale_date=date(2020, 1, 1)))


def test_stalled_project():
    assert "stalled_project" in recipes([sig("permit_stalled", 200, "remodel_addition")])
    assert "stalled_project" not in recipes([sig("permit_stalled", 200, "other")])   # not an effective signal


def test_downsizer():
    ok = owner(absentee=False, last_sale_date=date(2000, 1, 1), mortgage_open=False)
    assert "downsizer" in recipes([], ok)
    assert "downsizer" not in recipes([], owner(absentee=True, last_sale_date=date(2000, 1, 1), mortgage_open=False))
    assert "downsizer" not in recipes([], owner(absentee=False, last_sale_date=date(2000, 1, 1), mortgage_open=True))
    assert "downsizer" not in recipes([], owner(absentee=None, last_sale_date=date(2000, 1, 1), mortgage_open=False))
    assert "downsizer" not in recipes([], None)


def test_insurance_squeeze_only_active_when_fire_zones_exist():
    fire = sig("fire_hazard_zone", 0, details={"hazard_class": "Very High"})
    assert "insurance_squeeze" not in recipes([fire])                        # no fire data loaded
    assert "insurance_squeeze" in recipes([fire], data=["fire_zones"])
    mod = sig("fire_hazard_zone", 0, details={"hazard_class": "Moderate"})
    assert "insurance_squeeze" not in recipes([mod], data=["fire_zones"])


def test_financial_pressure():
    assert "financial_pressure" in recipes([sig("tax_default", 100)])
    assert "financial_pressure" in recipes([sig("stro_license_removed", 30)], owner(mortgage_open=True))
    assert "financial_pressure" not in recipes([sig("stro_license_removed", 30)], owner(mortgage_open=False))
    assert "financial_pressure" not in recipes([sig("tax_default", 900)])


def test_quiet_inheritance_never_matches():
    everything = [sig("tax_default", 1), sig("attom_recorder_transfer", 1)]
    assert "quiet_inheritance" not in recipes(everything, owner(), data=["fire_zones", "attom"])


# ---- reason text ---------------------------------------------------------------------------------
def rich_parcel():
    sigs = [
        sig("permit_approved", 14, "pre_sale_prep", {"approval_type": "Electrical Permit", "approval_id": "A1"}),
        sig("sb9_lot_split_estimate", 0, details={"zoning": "RS-1-7", "lot_sqft": 5000}, estimate=True),
        sig("tax_default", 200, details={"tax_defaulted_on": "2021-06-30", "list": "Notice, June 2026"}),
        sig("stro_license_active", 0, details={"license_id": "L9", "tier": "2"}),
        sig("permit_stalled", 300, "adu", {"approval_type": "Building Permit", "expire_date": "2026-01-10",
                                           "days_past_expiry": 312}),
    ]
    return score(sigs, owner(last_sale_date=date(1995, 3, 3), mortgage_open=False, absentee=True,
                             out_of_state=True, est_equity=9.0), cutoff=5.0)


def _digits(text):
    text = re.sub(r"SB \d+|1/[24] mile|\d+ ft", "", text)       # fixed wording, not facts
    return {int(t) for t in re.findall(r"\d+", text)}


def test_reason_text_only_states_facts_from_components():
    r = rich_parcel()
    text = r["reason_text"]
    assert text.endswith(".") and text[0].isupper()
    allowed = _digits(json.dumps([c["facts"] for c in r["components"]], default=str))
    assert _digits(text) <= allowed, (text, _digits(text) - allowed)
    # only the top components are used
    from territory.scoring_engine import phrase
    top = sorted(r["components"], key=lambda c: (-c["contribution"], c["key"]))[:CFG["reason_text"]["max_components"]]
    assert len(r["components"]) > len(top), "fixture must have more components than the reason shows"
    assert text == (", ".join(phrase(c) for c in top))[0].upper() + (", ".join(phrase(c) for c in top))[1:] + "."


def test_reason_text_never_mentions_a_signal_that_is_not_a_component():
    r = score([sig("permit_approved", 5, "pre_sale_prep", {"approval_type": "Electrical Permit"})])
    t = r["reason_text"].lower()
    for banned in ("sb 9", "sb 79", "tax", "fire", "short-term", "absentee", "mortgage", "owned"):
        assert banned not in t
    assert score()["reason_text"] == "No scoring signals on file."


def test_sample_and_estimate_labels_always_present():
    r = rich_parcel()
    for c in r["components"]:
        if c["kind"] == "owner":
            assert c["is_sample"] is True
    # every sample-derived phrase carries the label; every estimate carries (estimated)
    from territory.scoring_engine import phrase
    for c in r["components"]:
        p = phrase(c)
        assert ("(sample data)" in p) == c["is_sample"]
        assert ("(estimated)" in p) == c["is_estimate"]
    assert r["uses_sample_data"] is True
    assert "lot may qualify for an SB 9 split (estimated)" in phrase(
        next(c for c in r["components"] if c["key"] == "sb9_lot_split_estimate"))


def test_spec_example_wording():
    r = score([sig("permit_approved", 14, "pre_sale_prep", {"approval_type": "Re-roof Permit"}),
               sig("sb9_lot_split_estimate", 0, estimate=True, details={"zoning": "RS-1-7"})],
              owner(last_sale_date=date(1995, 3, 3), mortgage_open=False))
    assert r["reason_text"] == ("Re-roof Permit approved Nov 4, 2026, owned 31 years (sample data), "
                                "no open mortgage (sample data), lot may qualify for an SB 9 split (estimated).")


def test_no_sample_label_when_nothing_is_sample():
    r = score([sig("tax_default", 10, details={"tax_defaulted_on": "2025-06-30"})])
    assert "(sample data)" not in r["reason_text"] and not r["uses_sample_data"]


# ---- determinism ------------------------------------------------------------------------------------
def test_same_inputs_same_scores_in_any_order():
    base = [sig("tax_default", 100, details={"tax_defaulted_on": "2025-06-30"}),
            sig("permit_approved", 20, "pre_sale_prep", {"approval_type": "Electrical Permit"}),
            sig("permit_approved", 40, "adu", {"approval_type": "Building Permit"}),
            sig("sb9_lot_split_estimate", 0), sig("permit_stalled", 400, "adu")]
    own = owner(absentee=True, last_sale_date=date(1990, 1, 1))
    first = score(base, own, cutoff=0.5)
    for seed in range(5):
        shuffled = base[:]
        random.Random(seed).shuffle(shuffled)
        again = score(shuffled, own, cutoff=0.5)
        assert json.dumps(again, sort_keys=True, default=str) == json.dumps(first, sort_keys=True, default=str)
