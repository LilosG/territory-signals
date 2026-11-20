"""Deterministic validators: numbers, addresses, speculation, quotes, lead-brief and weekly rules, packet building."""
import json

import pytest

from territory.llm import validators as v
from territory.llm.tasks import lead_brief as lb
from territory.llm.tasks import permit_intent as pi
from territory.llm.tasks import weekly_brief as wb
from territory.scoring_engine import load_scoring_config

CFG = load_scoring_config()


def test_numbers_must_appear_in_the_packet_with_formatting_tolerance():
    packet = {"records": [{"text": "Owned 20 years", "date": "2026-09-14"}, {"text": "lot 13,000 sq ft, about $3,047,960"}]}
    assert v.check_numbers(["Owned 20 years; lot of 13000 sq ft; approved Sep 14, 2026; $3,047,960"], packet) == []
    bad = v.check_numbers(["Owned 25 years", "worth $4,000,000"], packet)
    assert len(bad) == 2 and any("25" in b for b in bad) and any("4,000,000" in b for b in bad)


@pytest.mark.parametrize("written", [
    "$3.05M (est.)", "$3.0M", "$3M", "$3.05 million", "$3,048,000", "$3,050,000", "about $3 million", "3.05M"])
def test_money_may_be_rounded_or_abbreviated_from_the_packet_number(written):
    packet = {"records": [{"text": "Equity in the top quarter; estimated equity about $3,047,960"}]}
    assert v.check_numbers([f"Estimated equity of {written}."], packet) == []


@pytest.mark.parametrize("written", ["$3.1M", "$3.04M", "$2.9M", "$3,100,000", "$4M", "$30M", "$304M"])
def test_money_that_does_not_round_from_the_packet_number_is_rejected(written):
    packet = {"records": [{"text": "estimated equity about $3,047,960"}]}
    assert v.check_numbers([f"Equity about {written}."], packet), written


def test_rounding_is_only_for_money_and_percentages_never_years_counts_or_dates():
    packet = {"records": [{"text": "Owned 20 years", "date": "2026-09-14"}, {"text": "2 building permits; 25.6% above the median; lot 13,040 sq ft"}]}
    assert v.check_numbers(["26% above the median", "about 26 percent"], packet) == []
    assert v.check_numbers(["25% above the median"], packet)                    # 25.6 rounds to 26, not 25
    assert v.check_numbers(["owned 2,030 years"], packet) and v.check_numbers(["3 building permits"], packet)
    assert v.check_numbers(["lot of 13,000 sq ft"], packet)                    # an area is a count, not rounded money


def test_other_addresses_are_rejected_but_the_subject_is_allowed():
    assert v.check_addresses(["Near 1234 Prospect St in La Jolla"], ["1234 PROSPECT ST"]) == []
    assert v.check_addresses(["Next to 99 Neighbor Ave"], ["1234 PROSPECT ST"])
    assert v.check_addresses(["No address here"], []) == []


@pytest.mark.parametrize("text", ["The owner needs the money", "likely struggling financially", "an elderly couple",
                                  "a widow", "probably divorcing", "owner is retiring", "financial hardship"])
def test_speculation_is_rejected_unless_a_record_says_it(text):
    assert v.check_speculation([text], {"records": [{"text": "Owned 20 years"}]})
    assert not v.check_speculation([text], {"records": [{"text": text}]})        # stated by a record: allowed


def test_single_family_is_not_a_household_claim():
    assert v.check_speculation(["a single-family home"], {"records": []}) == []


def test_quote_must_be_verbatim_and_at_most_12_words():
    d = "Install new A/C system connected to existing ducted furnace, upgrade main electrical panel to 200 amps"
    assert v.quote_in_source("upgrade main electrical panel", d) is None
    assert v.quote_in_source("UPGRADE main Electrical panel", d) is None                 # case-insensitive
    assert "do not appear" in v.quote_in_source("replace the roof", d)
    assert "13 words" in v.quote_in_source(" ".join(["word"] * 13), " ".join(["word"] * 20))
    assert v.quote_in_source("", d)


def test_permit_item_validation():
    item = pi.PermitItem(id=1, intent="maintenance", scope_tags=["hvac", "made_up"], confidence=0.8,
                         quote="replace furnace", reason="Routine equipment swap.")
    out, why = pi.validate_item(item, "Replace furnace and ducts")
    assert why is None and out["scope_tags"] == ["hvac"]
    out, why = pi.validate_item(item, "Kitchen remodel")
    assert out is None and "do not appear" in why
    with pytest.raises(Exception):
        pi.PermitItem(id=1, intent="selling_soon", scope_tags=[], confidence=0.5, quote="x", reason="y")   # not in the enum
    with pytest.raises(Exception):
        pi.PermitItem(id=1, intent="maintenance", scope_tags=[], confidence=1.5, quote="x", reason="y")


# ---- lead brief ---------------------------------------------------------------------------------------------
def component(key, kind="signal", contribution=10.0, group=None, facts=None, **kw):
    c = {"key": key, "kind": kind, "contribution": contribution, "facts": facts or {}, "is_sample": False,
         "is_estimate": False, "group": group, "family": "permits", "signal_id": f"sig-{key}", "source_key": "dev_permits",
         "signal_date": "2026-09-14", "confidence": 0.95}
    c.update(kw)
    return c


def packet():
    comps = [
        component("permit_approved:pre_sale_prep", group="pre_sale_prep",
                  facts={"group": "pre_sale_prep", "issue_date": "2026-09-14", "permit_count": 1, "permit_label": "Plumbing work"}),
        component("owner:years_owned", kind="owner", facts={"years_owned": 20}, is_sample=True, provider="sample", as_of="2026-11-18"),
        component("tax_default", group="distress", facts={"notice": "June 2026", "notice_date": "2026-07-01", "tax_defaulted_on": "2021-06-30"}),
        component("owner:ownership_transfer", kind="owner", facts={}, provider="sample", as_of="2026-11-18"),
    ]
    parcel = {"apn": "1", "situs_address": "1234 PROSPECT ST", "neighborhood": "La Jolla", "zoning": "RS-1-2", "lot_sqft": 13000.0, "year_built": 1962}
    return lb.build_packet(parcel, {"id": "S1", "components": comps, "recipe_matches": ["pre_list_prep", "financial_pressure"]},
                           {"pre_list_prep": "Pre-list prep", "financial_pressure": "Financial pressure"}, CFG)


def test_packet_holds_only_database_facts_and_never_sensitive_ones():
    pk = packet()
    texts = " ".join(r["text"] for r in pk.packet["records"])
    assert "tax" not in texts.lower() and "transfer" not in texts.lower() and "Financial pressure" not in texts
    assert "Plumbing work approved Sep 14, 2026" in texts and "playbook" not in texts.lower()
    assert {r["id"] for r in pk.packet["records"]} == set(pk.real_ids)
    assert pk.real_ids["R2"] == "sig-permit_approved:pre_sale_prep" and pk.real_ids["R3"] == "owner:years_owned"
    assert pk.real_ids["R1"] == "parcel:1" and pk.sample["R3"] is True
    assert all(set(r) >= {"id", "source", "date", "confidence", "is_sample", "is_estimate"} for r in pk.packet["records"])


def test_packet_carries_the_meaning_of_each_signal_and_the_rationale_of_each_matched_recipe_as_citable_records():
    pk = packet()
    kinds = {r["id"]: r["kind"] for r in pk.packet["records"]}
    assert [k for k in kinds.values()] == ["parcel", "signal", "owner", "meaning", "meaning", "pattern"]
    by_real = {pk.real_ids[r["id"]]: r["text"] for r in pk.packet["records"]}
    meanings = lb.load_meanings()
    assert meanings["permit_approved:pre_sale_prep"] in by_real["meaning:permit_approved:pre_sale_prep"]
    assert meanings["owner:years_owned"] in by_real["meaning:owner:years_owned"]
    assert CFG["recipes"]["pre_list_prep"]["rationale"] in by_real["recipe:pre_list_prep"]     # from the recipe definition
    assert "meaning:owner:ownership_transfer" not in by_real and "recipe:financial_pressure" not in by_real   # sensitive: never
    assert not any("tax" in t.lower() for t in by_real.values())


def test_every_scoring_component_and_public_recipe_has_a_plain_meaning_in_config():
    from territory.export_catalog import component_specs
    meanings = lb.load_meanings()
    missing = [c["key"] for c in component_specs(CFG) if c["key"] not in ("owner:ownership_transfer", "tax_default") and c["key"] not in meanings]   # sensitive: never in a brief
    assert missing == []
    no_rationale = [k for k, r in CFG["recipes"].items() if k not in lb.SENSITIVE_RECIPES and r.get("active") is not False
                    and not r.get("rationale")]
    assert no_rationale == []


def test_nothing_to_say_means_no_packet():
    parcel = {"apn": "1", "situs_address": "x", "neighborhood": "La Jolla"}
    assert lb.build_packet(parcel, {"id": "S", "components": [component("tax_default", group="distress")], "recipe_matches": []}, {}, CFG) is None


def good_brief(**over):
    d = {"headline": "Remodel work by a long-time owner",
         "summary": "Cosmetic or remodel work was approved on this home, the kind that often goes in before a sale. "
                    "The owner has held it a long time, so the work may not be a quick flip.",
         "suggested_angle": "Ask whether the approved work is meant to get the home ready for sale and offer a pre-listing walkthrough.",
         "claims": [{"text": "Plumbing work approved Sep 14, 2026.", "record_ids": ["R2"]},
                    {"text": "Owned 20 years.", "record_ids": ["R3"]},
                    {"text": "Work of this kind often goes in before a sale.", "record_ids": ["R4"]}]}
    d.update(over)
    return lb.LeadBriefOut.model_validate(d)


def test_valid_brief_maps_refs_to_real_ids_and_flags_sample():
    stored, problems, cited, sample = lb.validate(good_brief(), packet())
    assert problems == [] and cited == ["sig-permit_approved:pre_sale_prep", "owner:years_owned",
                                        "meaning:permit_approved:pre_sale_prep"] and sample is True
    assert stored["claims"][0]["record_ids"] == ["sig-permit_approved:pre_sale_prep"]


def test_not_sample_when_no_cited_record_is_sample():
    b = good_brief(claims=[{"text": "Plumbing work approved Sep 14, 2026.", "record_ids": ["R2"]}])
    assert lb.validate(b, packet())[3] is False


def test_a_brief_may_cite_a_recipe_rationale_or_a_signal_meaning():
    b = good_brief(claims=[{"text": "Plumbing work approved Sep 14, 2026.", "record_ids": ["R2"]},
                           {"text": "A permit for remodel work was approved on a home held 10 or more years.", "record_ids": ["R6"]},
                           {"text": "Remodel permits often come before a sale.", "record_ids": ["R4"]}])
    stored, problems, cited, _ = lb.validate(b, packet())
    assert problems == [] and cited == ["sig-permit_approved:pre_sale_prep", "recipe:pre_list_prep", "meaning:permit_approved:pre_sale_prep"]


@pytest.mark.parametrize("change,needle", [
    ({"claims": [{"text": "Plumbing work.", "record_ids": []}]}, "cites no record"),
    ({"claims": [{"text": "Plumbing work.", "record_ids": ["R99"]}]}, "not in the packet"),
    ({"summary": "Owned 25 years. A second sentence."}, "25"),
    ({"summary": "One sentence only."}, "1 sentences"),
    ({"headline": "one two three four five six seven eight nine ten eleven"}, "10 words"),
    ({"summary": "Sits next to 99 Other Ave. Owned 20 years."}, "address"),
    ({"summary": "The owner is struggling financially. Owned 20 years."}, "speculation"),
    # v2 style rules
    ({"headline": "Recent permits and a large La Jolla lot"}, "Recent permits"),
    ({"headline": "RS-1-2 lot with SB 9 potential"}, "zoning code or jargon"),
    ({"headline": "Lot that may allow an ADU"}, "zoning code or jargon"),
    ({"headline": "Pre-sale prep work on a long-held home"}, "internal category name"),
    ({"headline": "Pre-list prep home with a long-time owner"}, "internal category name"),
    ({"summary": "This 13,000 sq ft lot is zoned RS-1-2 and was approved Sep 14, 2026. The owner has held it 20 years."}, "restates the page header"),
    ({"summary": "Work was approved in September, and the owner has held the home 20 years. Both are in the header."}, "restates the page header"),
    ({"summary": "The owner has held the home 20 years (sample data). Work was approved."}, "sample data"),
    ({"summary": "It matches our playbook for pre-sale work. The owner has held it a long time."}, "playbook"),
    ({"summary": "It matches a recipe for long-held homes. Work was approved."}, "recipe"),
    ({"suggested_angle": "Offer a La Jolla market update and recent permit activity nearby."}, "generic market-update"),
    ({"suggested_angle": "Ask about the remodel. Then offer a walkthrough."}, "one sentence"),
    ({"headline": "  "}, "empty output"),
    ({"headline": "Long-time owner prepping the home to sell"}, "intent as fact"),
    ({"summary": "The owner is planning to sell soon. Cosmetic work was approved."}, "intent as fact"),
    ({"summary": "Our notes read the missing mortgage as free and clear. Cosmetic work was approved."}, "own configuration or notes"),
    ({"summary": " ".join(["Cosmetic work was approved on this home and it is the kind of work that goes in before a sale, by an owner who has held the home for a long time."] * 3)}, "words (max 80)"),
    ({"claims": [{"text": "Work of this kind often goes in before a sale.", "record_ids": ["R4"]},
                 {"text": "Owners who have held a home long may be ready to sell.", "record_ids": ["R6"]}]}, "only explanations"),
])
def test_brief_rejections(change, needle):
    stored, problems, *_ = lb.validate(good_brief(**change), packet())
    assert stored is None and needle in " ".join(problems)


def test_one_header_fact_is_allowed_when_it_supports_the_why():
    b = good_brief(summary="Remodel work was approved on a home the owner has held for 20 years, the kind of owner who "
                           "may be ready for a change. Cosmetic updates often go in before a sale.")
    assert lb.validate(b, packet())[1] == []


# ---- weekly brief -----------------------------------------------------------------------------------------------
FACTS = {"week": {"start": "2026-11-09", "end": "2026-11-16"}, "baseline": {"kind": "none", "compared_with": None},
         "territory": {"strong_leads_now": 12, "top_movers": [{"address": "100 Example St"}]},
         "neighborhoods": {"La Jolla": {"strong_leads_now": 7}}}
NEWS = ("This week brought steady activity across our neighborhoods, with 31 homeowners pulling permits for everyday upgrades "
        "like new heating and cooling systems, fresh paint and plumbing work. Many of these projects keep homes comfortable and "
        "efficient for years to come. If you are curious what recent improvements mean for the value of your home, we are happy "
        "to share a simple, no-pressure summary of what is happening on your street and nearby.")


def weekly(**over):
    d = {"title": "A steady week", "intro": "Activity held steady. We saw 12 strong opportunities.",
         "sections": [{"neighborhood": "La Jolla", "bullets": ["7 strong opportunities."]}], "newsletter_paragraph": NEWS}
    d.update(over)
    return wb.WeeklyOut.model_validate(d)


def test_news_fixture_is_within_word_limits():
    assert 60 <= len(NEWS.split()) <= 90


def test_weekly_numbers_must_come_from_the_facts():
    facts = {**FACTS, "territory": {**FACTS["territory"], "x": 31}}
    assert wb.validate(weekly(), facts) == []
    probs = wb.validate(weekly(), FACTS)                 # 31 is not in these facts
    assert any("31" in p for p in probs)


@pytest.mark.parametrize("news,needle", [
    (NEWS + " Call us about 100 Example St.", "address"),
    (NEWS.replace("homeowners", "leads"), "internal"),
    (NEWS.replace("paint", "estimated paint"), "internal"),
    (NEWS.replace("plumbing work", "tax default notices"), "sensitive"),
    (NEWS.replace("fresh paint", "Pre-list prep"), "recipe name"),
    ("Too short to be a paragraph.", "words"),
])
def test_newsletter_paragraph_rules(news, needle):
    facts = {**FACTS, "territory": {**FACTS["territory"], "x": 31}}
    probs = wb.validate(weekly(newsletter_paragraph=news), facts)
    assert any(needle in p for p in probs), probs


def test_weekly_structure_rules():
    facts = {**FACTS, "territory": {**FACTS["territory"], "x": 31}}
    assert any("more than 4" in p for p in wb.validate(weekly(sections=[{"neighborhood": "La Jolla", "bullets": ["a"] * 5}]), facts))
    assert any("unknown neighborhood" in p for p in wb.validate(weekly(sections=[{"neighborhood": "Nowhere", "bullets": ["a"]}]), facts))
    assert not any("intro has" in p for p in wb.validate(weekly(intro="Only one sentence."), facts))      # 5H: at most 2, not exactly 2
    assert any("intro has 3" in p for p in wb.validate(weekly(intro="One thing. Two things. Three things."), facts))
    assert any("tax-default" in p for p in wb.validate(weekly(intro="Tax default counts rose. Second sentence."), facts))


# ---- shadow-mode agreement report -----------------------------------------------------------------------------
def test_agreement_report_counts_per_group_and_samples_disagreements():
    from territory.llm import agreement
    rows = [("a", "pre_sale_prep", "Replace furnace", "prep_to_sell", "0.9"), ("b", "pre_sale_prep", "Replace water heater", "maintenance", "0.9"),
            ("c", "adu", "Build ADU", "investment_or_redevelopment", "0.9"), ("d", "other", "Sign", "unclear", "0.5")]
    text = agreement.render(rows, "Model `m`.", "Cost $0.01.")
    assert "| pre_sale_prep | 2 | 1 | 50.0% |" in text and "| adu | 1 | 1 | 100.0% |" in text and "| other | 1 | n/a | n/a |" in text
    assert "Overall (groups with an implied intent): 2 of 3 = 66.7%" in text
    assert "1 sample disagreements (1 in total)" in text and "Replace water heater | pre_sale_prep | maintenance" in text


def test_quote_matching_ignores_case_punctuation_and_spacing_but_not_paraphrase():
    d = "Construction change to project 354553. Reconfigure master bathroom,  replace shower w/ tub (E) SDU."
    assert v.quote_in_source('"Reconfigure master bathroom, replace shower w/ tub"', d) is None
    assert v.quote_in_source("reconfigure   MASTER bathroom", d) is None
    assert v.quote_in_source("reconfigure the master bathroom", d)            # paraphrase: rejected
    assert v.quote_in_source("bathroom ... SDU", d)                           # stitched fragments: rejected


def test_permit_scope_limits_to_recent_or_high_scoring_parcels(db):
    from datetime import date
    from test_llm_tasks_db import add_permit, seed_scored
    from territory.config import PermitScope
    seed_scored(db)
    add_permit(db, "6000000000", "OLD-1", "Replace the old water heater at this house", on=date(2015, 1, 1))
    add_permit(db, "6000000001", "NEW-1", "Replace the new water heater at this house", on=date(2026, 10, 1))
    everything = {p.record_id for p in pi.load_permits(db)}
    recent_only = {p.record_id for p in pi.load_permits(db, scope=PermitScope(months=36, min_lead_score=100), today=date(2026, 11, 20))}
    with_scores = {p.record_id for p in pi.load_permits(db, scope=PermitScope(months=36, min_lead_score=0), today=date(2026, 11, 20))}
    assert "OLD-1" in everything and "OLD-1" not in recent_only and "NEW-1" in recent_only
    assert "OLD-1" in with_scores                                              # old permit, but the parcel scores >= the minimum


# ---- weekly brief v2 (Phase 5G): lead with what is new, leave out what did not change, no internal wording -----------
FULL = {"week": {"start": "2026-11-12", "end": "2026-11-19"}, "baseline": {"kind": "earliest_available", "compared_with": "2026-11-03"},
        "territory": {"strong_leads_now": 7, "new_strong_leads": 0, "new_pre_sale_permits": 4, "new_str_removals": 0,
                      "tax_default_new_this_week": 0, "tax_default_total": 39,
                      "recipe_counts": {"Pre-list prep": {"now": 16, "before": 16, "change": 0},
                                        "Builder bait": {"now": 364, "before": 366, "change": -2},
                                        "Downsizer": {"now": 9, "before": None, "change": None}},
                      "top_movers": [{"address": "1260 Rhoda Dr", "neighborhood": "La Jolla", "score_before": 66, "score_now": 37, "change": -29}]},
        "neighborhoods": {"La Jolla": {"strong_leads_now": 3, "new_strong_leads": 0, "new_pre_sale_permits": 4, "new_str_removals": 0,
                                       "new_permits_by_type": {"remodel or cosmetic permits": 4},
                                       "tax_default_new_this_week": 1, "tax_default_total": 15, "recipe_counts": {}, "top_movers": []},
                          "Mission Beach": {"strong_leads_now": 1, "new_strong_leads": None, "new_pre_sale_permits": 0, "new_str_removals": 0,
                                            "tax_default_new_this_week": 0, "tax_default_total": 0, "recipe_counts": {}, "top_movers": []}}}


def test_the_model_sees_only_what_is_new_or_changed():
    view = wb.model_view(FULL)
    assert "baseline" not in view
    assert view["territory"] == {"strong_leads_now": 7, "changes_by_home_type": {"Builder bait": {"now": 364, "change": -2}},
                                 "top_movers": FULL["territory"]["top_movers"]}
    assert view["neighborhoods"]["La Jolla"] == {"strong_leads_now": 3, "new_this_week": {"remodel or cosmetic permits": 4},
                                                 "tax_default_new_this_week": 1, "tax_default_total": 15}
    assert view["neighborhoods"]["Mission Beach"] == {"strong_leads_now": 1}             # nothing new: only the count
    text = json.dumps(view)
    assert "new_strong_leads" not in text and "new_str_removals" not in text and "Pre-list prep" not in text


def test_every_number_in_the_view_is_still_in_the_full_facts():
    from territory.llm.validators import check_numbers
    assert check_numbers([json.dumps(wb.model_view(FULL))], FULL) == []


@pytest.mark.parametrize("bullet", ["No new pre-sale permits in Mission Beach.", "None new this week in La Jolla.",
                                    "Nothing new to report.", "Zero new strong leads.", "Pre-list prep counts are unchanged.",
                                    "0 new rental removals."])
def test_weekly_must_leave_out_categories_with_no_change(bullet):
    facts = {**FACTS, "territory": {**FACTS["territory"], "x": 31}}
    probs = wb.validate(weekly(sections=[{"neighborhood": "La Jolla", "bullets": [bullet]}]), facts)
    assert any("leave out categories with no change" in p for p in probs), probs
    assert any("leave out" in p for p in wb.validate(weekly(intro="There were no new permits. We saw 12 strong opportunities."), facts))


@pytest.mark.parametrize("text", ["Compared with the baseline, counts eased.", "Our watch categories moved.",
                                  "Earliest available data shows a dip.", "Our recipes matched 12 homes.", "Sample data shows 12 homes."])
def test_weekly_must_not_use_internal_wording(text):
    facts = {**FACTS, "territory": {**FACTS["territory"], "x": 31}}
    probs = wb.validate(weekly(sections=[{"neighborhood": "La Jolla", "bullets": [text]}]), facts)
    assert any("internal wording" in p for p in probs), probs


def test_a_news_led_weekly_brief_passes():
    facts = {**FACTS, "territory": {**FACTS["territory"], "new_pre_sale_permits": 4, "x": 31}}
    good = weekly(title="Pre-sale permits lead La Jolla",
                  intro="La Jolla has 4 new pre-sale permits this week. The territory holds 12 strong leads.",
                  sections=[{"neighborhood": "La Jolla", "bullets": ["4 new pre-sale permits.", "7 strong leads now."]}])
    assert wb.validate(good, facts) == []
    # the same count stated twice in the title and intro is rejected (Phase 5H)
    assert any("repeats the count 4" in p for p in wb.validate(weekly(title="4 new pre-sale permits in La Jolla", intro=good.intro, sections=[{"neighborhood": "La Jolla", "bullets": ["7 strong leads now."]}]), facts))


def test_a_newsletter_may_not_make_claims_that_are_not_in_the_facts():
    facts = {**FACTS, "territory": {**FACTS["territory"], "x": 31}}
    for claim in ("Late fall is often a quieter time along the coast.", "Prices are holding steady.", "Demand is strong this season."):
        news = NEWS.replace("Many of these projects", claim + " Many of these projects")
        probs = wb.validate(weekly(newsletter_paragraph=news), facts)
        assert any("general claim" in p for p in probs), (claim, probs)
    assert not any("general claim" in p for p in wb.validate(weekly(), facts))


@pytest.mark.parametrize("text,ok", [
    ("Long-time owner prepping the home to sell", False),
    ("The owner plans to sell this year.", False),
    ("The owner is planning to list in spring.", False),
    ("An owner who may plan to sell soon.", True),                       # hedged
    ("Owners like this might be preparing to sell.", True),
    ("Worth asking whether they plan to sell.", True),
    ("Work that often goes in before a sale.", True),
    ("Owners who may want a smaller home.", True),
])
def test_intent_to_sell_is_rejected_unless_hedged(text, ok):
    assert (v.check_intent_and_meta([text]) == []) is ok


# ---- repetition (Phase 5H) ----------------------------------------------------------------------------------------------
from territory.llm.validators import check_repetition


def test_repetition_flags_the_same_count_about_the_same_thing():
    p = check_repetition([["Busy week in La Jolla.", "There are 4 new pre-sale permits. 4 remodel permits were approved."]])
    assert len(p) == 1 and "count 4" in p[0]
    assert check_repetition([["Four new permits arrived. Then 4 more permits were filed."]])         # spelled-out numbers count


def test_repetition_allows_different_facts_dates_scores_and_separate_blocks():
    assert not check_repetition([["5 new permits arrived.", "5 homes reached a strong score."]])    # same number, different things
    assert not check_repetition([["Permits approved Nov 10, 2026.", "More permits approved Nov 10, 2026."]])   # a date is not a count
    assert not check_repetition([["1260 Rhoda Dr: 40 to 66.", "1300 Rhoda Dr: 40 to 66."]])         # score moves are not counts
    assert not check_repetition([["2 new permits in La Jolla."], ["2 new permits in Pacific Beach."]])   # blocks are separate (one per neighborhood)
