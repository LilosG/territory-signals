"""Deterministic validators: numbers, addresses, speculation, quotes, lead-brief and weekly rules, packet building."""
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
    assert len(bad) == 2 and "25" in bad[0] and "4000000" in bad[1]


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
    assert "Pre-list prep" in texts and "Plumbing work approved Sep 14, 2026" in texts
    assert {r["id"] for r in pk.packet["records"]} == set(pk.real_ids)
    assert pk.real_ids["R2"] == "sig-permit_approved:pre_sale_prep" and pk.real_ids["R3"] == "owner:years_owned"
    assert pk.real_ids["R1"] == "parcel:1" and pk.sample["R3"] is True
    assert all(set(r) >= {"id", "source", "date", "confidence", "is_sample", "is_estimate"} for r in pk.packet["records"])


def test_nothing_to_say_means_no_packet():
    parcel = {"apn": "1", "situs_address": "x", "neighborhood": "La Jolla"}
    assert lb.build_packet(parcel, {"id": "S", "components": [component("tax_default", group="distress")], "recipe_matches": []}, {}, CFG) is None


def good_brief(**over):
    d = {"headline": "Recent plumbing permit and long ownership", "summary": "This home had plumbing work approved in September. "
         "The owner has held it for 20 years (sample data).", "suggested_angle": "Offer a neighborhood market update.",
         "claims": [{"text": "Plumbing work approved Sep 14, 2026.", "record_ids": ["R2"]},
                    {"text": "Owned 20 years (sample data).", "record_ids": ["R3"]}]}
    d.update(over)
    return lb.LeadBriefOut.model_validate(d)


def test_valid_brief_maps_refs_to_real_ids_and_flags_sample():
    stored, problems, cited, sample = lb.validate(good_brief(), packet())
    assert problems == [] and cited == ["sig-permit_approved:pre_sale_prep", "owner:years_owned"] and sample is True
    assert stored["claims"][0]["record_ids"] == ["sig-permit_approved:pre_sale_prep"]


def test_not_sample_when_no_cited_record_is_sample():
    b = good_brief(claims=[{"text": "Plumbing work approved Sep 14, 2026.", "record_ids": ["R2"]}])
    assert lb.validate(b, packet())[3] is False


@pytest.mark.parametrize("change,needle", [
    ({"claims": [{"text": "Plumbing work.", "record_ids": []}]}, "cites no record"),
    ({"claims": [{"text": "Plumbing work.", "record_ids": ["R99"]}]}, "not in the packet"),
    ({"summary": "Owned 25 years. A second sentence."}, "25"),
    ({"summary": "One sentence only."}, "1 sentences"),
    ({"headline": "one two three four five six seven eight nine ten eleven twelve thirteen"}, "12 words"),
    ({"summary": "Sits next to 99 Other Ave. Owned 20 years."}, "address"),
    ({"summary": "The owner is struggling financially. Owned 20 years."}, "speculation"),
])
def test_brief_rejections(change, needle):
    stored, problems, *_ = lb.validate(good_brief(**change), packet())
    assert stored is None and needle in " ".join(problems)


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
    assert any("2)" in p for p in wb.validate(weekly(intro="Only one sentence."), facts))
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
