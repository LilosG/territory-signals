"""Template rules (D10, D11): length, structure, no internal labels, no market claims, signature, blocked reasons."""
import json
import re

import pytest

from territory.config import TeamMember, TeamProfile, load_client
from territory.export_catalog import build_catalog
from territory.outreach_render import (
    BLOCKED_AGENT, BLOCKED_OFFICE, CALL_REMINDER, CALL_WORDS_MAX, CHANNEL_FILE, EMAIL_OPT_OUT, EMAIL_WORDS,
    GENERAL, LETTER_WORDS, TEMPLATES_DIR, all_template_files, blocked_reason, call_to_action, counted_text, dre_text,
    load_template, render, signature, signoff_lines, street_of, word_count,
)
from territory.scoring_engine import load_scoring_config

CLIENT = load_client("kaiser-team")
CFG = load_scoring_config()
RECIPES = [r for r in CLIENT.enabled_recipes() if CFG["recipes"][r].get("active") is not False]
CHANNELS = list(CHANNEL_FILE)
AGENT = TeamMember(name="Pat Test-Agent", email="pat@example.test", role="agent",
                   dre_license="DRE #01234567", phone="(619) 555-0100")
TEAM = TeamProfile(display_name="The Kaiser Team", brokerage="Example Brokerage Group",
                   office_address="1 Test Way, San Diego, CA 92037")
SHORT_SALUTATION = "To the owners of 2651 Greentree Ln,"                       # the shortest greeting we produce
LONG_SALUTATION = "To the Trustee of the John, Mary and James Smith Revocable Family Trust,"   # the longest
SITUS = "2651 Greentree Ln"

BANNED = [
    r"\bneighbors?\b", r"public records?", r"records show", r"our records", r"we (know|noticed|saw|found)",
    r"according to", r"\bdeath\b", r"\bdied\b", r"\bdeceased\b", r"passed away", r"inherit", r"probate",
    r"\bestate of\b", r"tax[- ]default", r"delinquen", r"\bdebt", r"foreclos", r"non-?renewal", r"insurance",
    r"\blien", r"\bmortgage", r"distress", r"\bdefault", r"\bbankrupt", r"\bpower[- ]to[- ]sell",
]
TEAM_CLAIMS = [r"\byears? in (the )?business\b", r"\btop[- ]producer", r"#\s?1\b", r"number one", r"\branked\b",
               r"\baward", r"\bsold \d", r"\d+ homes", r"\bvolume\b", r"\bsales record", r"\bexperience[d]? with \d"]
MARKET_CLAIMS = [r"\brising\b", r"\bappreciat", r"\bdemand\b", r"\bbuilders?\b", r"paying more", r"\bhot market",
                 r"\bbooming\b", r"\bskyrocket", r"\bsurg", r"low inventory", r"\bmultiple offers", r"\bbidding"]
INTERNAL_LABELS = [r"\(estimated\)", r"\(sample data\)", r"\bestimated\b", r"\bsample\b", r"\bscores?\b",
                   r"\bsignals?\b", r"\btier\b", r"\brecipe\b", r"\bSB ?9\b", r"\bSB ?79\b", r"\bconfidence\b"]


def internal_names():
    """Every signal type, group, component key, recipe key and band name in the catalog."""
    cat = build_catalog(CLIENT)
    names = {t["key"] for t in cat["signal_types"]} | {g["key"] for g in cat["signal_groups"]}
    names |= {c["key"] for c in cat["components"]} | {r["key"] for r in cat["recipes"]}
    return {n for n in names if "_" in n or ":" in n}


def tpl(recipe, channel):
    return load_template(recipe, channel)


def rendered(recipe, channel, salutation=SHORT_SALUTATION, agent=AGENT, team=TEAM):
    return render(channel, tpl(recipe, channel), salutation, "La Jolla", SITUS, agent, team)


def all_renders():
    for recipe in RECIPES + [GENERAL]:
        for ch in CHANNELS:
            yield recipe, ch, rendered(recipe, ch)


def test_every_enabled_recipe_and_the_general_fallback_has_all_three_channels():
    for recipe in RECIPES + [GENERAL]:
        for fname in CHANNEL_FILE.values():
            assert (TEMPLATES_DIR / recipe / f"{fname}.md").exists(), f"missing {recipe}/{fname}.md"
    assert "quiet_inheritance" not in RECIPES
    assert len(all_template_files()) == (len(RECIPES) + 1) * 3


def test_a_recipe_without_templates_falls_back_to_general():
    assert load_template("quiet_inheritance", "mail").key == "general/letter"
    assert load_template("builder_bait", "mail").key == "builder_bait/letter"


# ---- length ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
def test_letter_70_to_130_words(recipe):
    lo, hi = LETTER_WORDS
    assert word_count(rendered(recipe, "mail", LONG_SALUTATION).text) <= hi          # every field, longest greeting
    assert word_count(rendered(recipe, "mail", SHORT_SALUTATION).text) >= lo         # every field, shortest greeting


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
def test_email_50_to_100_words_with_a_subject_naming_the_street(recipe):
    lo, hi = EMAIL_WORDS
    r = rendered(recipe, "email", LONG_SALUTATION)
    assert r.subject and r.text.startswith(f"Subject: {r.subject}\n") and "Greentree Ln" in r.subject
    assert "2651" not in r.subject
    assert word_count(counted_text("email", r)) <= hi
    assert word_count(counted_text("email", rendered(recipe, "email", SHORT_SALUTATION))) >= lo


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
def test_call_script_under_90_words_with_permission_opener_and_reminder(recipe):
    r = rendered(recipe, "call_task")
    assert word_count(r.text) < CALL_WORDS_MAX
    assert r.text.rstrip().endswith(CALL_REMINDER)
    assert CALL_REMINDER == "Manual dial only. Check Do Not Call status before calling."
    first = r.text.split("\n\n")[0]
    assert "quick question" in first and first.strip().endswith("?")
    assert "Pat Test-Agent" in first and "DRE #01234567" in first and "The Kaiser Team" in first


# ---- structure -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
@pytest.mark.parametrize("channel", ["mail", "email"])
def test_structure_focus_why_now_one_offer_one_call_to_action_signature(recipe, channel):
    r = rendered(recipe, channel)
    paras = r.body.split("\n\n")
    assert len(paras) == 3                                                    # focus + why now / offer / CTA
    assert paras[0].startswith("I focus on La Jolla")
    assert "one-page summary" not in r.text
    assert "I can " in paras[1] or "I'll " in paras[1]                          # one concrete offer
    cta = paras[2]
    assert cta.endswith("Call or text me at (619) 555-0100, or email pat@example.test.")
    assert r.text.split("\n\n")[-1 if channel == "mail" else -2] == (
        "Pat Test-Agent · The Kaiser Team · Example Brokerage Group · DRE #01234567")


def test_the_builder_bait_letter_meets_the_quality_bar():
    text = rendered("builder_bait", "mail", "Dear John Smith,").text
    assert text == (
        "Dear John Smith,\n\n"
        "I focus on La Jolla, and California's recent zoning changes have opened new options for some lots like "
        "yours on Greentree Ln.\n\n"
        "If you've wondered whether your property is worth more as a home or as a lot, I can put together a short "
        "side-by-side: what it would likely sell for as it stands, and what comparable lots nearby have sold for.\n\n"
        "No obligation, just numbers you can keep. Call or text me at (619) 555-0100, or email pat@example.test.\n\n"
        "Pat Test-Agent · The Kaiser Team · Example Brokerage Group · DRE #01234567")


OFFERS = {   # the one concrete offer of each recipe (phrases that must be in the letter body)
    "builder_bait": ["as a home or as a lot", "comparable lots nearby"],
    "tired_landlord": ["net if sold today versus continuing to rent", "1031 exchange", "tax advisor"],
    "str_exit": ["short-term rental rules", "sell, rent it long term, or hold", "likely sell for"],
    "pre_list_prep": ["updates actually pay off before selling", "which don't"],
    "stalled_project": ["as it stands", "once finished"],
    "downsizer": ["Prop 19", "55 and over", "tax advisor"],
    "financial_pressure": ["neutral, no-pressure summary", "would likely sell for today"],
    "insurance_squeeze": ["neutral, no-pressure summary", "would likely sell for today"],
    "general": ["current value summary"],
}


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
def test_each_recipe_makes_its_own_concrete_offer(recipe):
    body = rendered(recipe, "mail").body
    for phrase in OFFERS[recipe]:
        assert phrase in body, f"{recipe}: {phrase!r}"
    if recipe not in ("financial_pressure", "insurance_squeeze", "general"):
        other = rendered("general", "mail").body
        assert body != other


# ---- what homeowners must never see ----------------------------------------------------------------------
@pytest.mark.parametrize("recipe,channel,r", [(a, b, c) for a, b, c in all_renders()],
                         ids=lambda x: x if isinstance(x, str) else "")
def test_no_internal_labels_in_homeowner_text(recipe, channel, r):
    text = r.text + " " + (r.subject or "")
    for pat in INTERNAL_LABELS:
        assert not re.search(pat, text, re.I), f"{recipe}/{channel}: internal label {pat!r}"
    for name in internal_names():
        assert name not in text, f"{recipe}/{channel}: internal name {name!r}"
    assert "[" not in text and "{" not in text                              # no banner, no unfilled placeholder


def test_template_files_themselves_contain_no_internal_labels():
    for f in all_template_files():
        raw = f.read_text()
        body = raw.split("---\n", 2)[2]                                      # the front matter lists fact keys
        for pat in INTERNAL_LABELS:
            assert not re.search(pat, body, re.I), f"{f.name}: {pat!r}"


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
@pytest.mark.parametrize("channel", CHANNELS)
def test_banned_phrasing_claims_and_wording_never_appear(recipe, channel):
    r = rendered(recipe, channel)
    text = (r.text + " " + (r.subject or "")).lower()
    for pat in BANNED + TEAM_CLAIMS + MARKET_CLAIMS:
        assert not re.search(pat, text), f"{recipe}/{channel}: {pat!r}"
    assert len(re.findall(r"no[- ]obligation", text)) <= 1                    # said at most once
    for filler in ("no time at all", "never pressure", "glad to"):
        assert filler not in text
    assert text.count("i would be") == 0


def test_a_sourced_number_would_be_needed_for_market_claims():
    for f in all_template_files():                                            # templates carry no figures at all
        body = f.read_text().split("---\n", 2)[2]
        assert not re.search(r"\$|\d+%|percent", body)


# ---- facts a template relies on -----------------------------------------------------------------------------
def test_facts_listed_by_templates_are_only_the_ones_the_text_states():
    assert tpl("builder_bait", "mail").facts == ("sb9_lot_split_estimate", "sb79_transit_estimate")
    assert tpl("str_exit", "mail").facts == ("stro_license_removed",)
    assert tpl("tired_landlord", "mail").facts == ("owner:absentee", "owner:out_of_state")
    assert tpl("stalled_project", "mail").facts == ("permit_stalled",)
    for recipe in ("pre_list_prep", "downsizer", "financial_pressure", "insurance_squeeze", GENERAL):
        assert all(tpl(recipe, ch).facts == () for ch in CHANNELS)


def test_used_parcel_fields_are_reported():
    assert set(rendered("general", "mail").used_fields) == {"neighborhood", "situs_address"}
    assert set(rendered("general", "call_task").used_fields) == {"neighborhood", "situs_address"}
    assert set(rendered("builder_bait", "mail").used_fields) == {"neighborhood", "situs_address"}
    assert set(rendered("pre_list_prep", "mail").used_fields) == {"neighborhood"}


def test_street_name_drops_the_house_number():
    assert street_of("2651 Greentree Ln") == "Greentree Ln"
    assert street_of("100 N Prospect St") == "N Prospect St"
    assert street_of("") == "your street"


# ---- signature, call to action, blocked reasons ---------------------------------------------------------------
def test_signature_and_call_to_action_variants():
    assert signature(AGENT, TEAM) == "Pat Test-Agent · The Kaiser Team · Example Brokerage Group · DRE #01234567"
    solo = TeamMember(name="Pat", email="p@example.test", role="agent", dre_license="01234567")
    assert signoff_lines(solo, TeamProfile(display_name="The Kaiser Team")) == ["Pat", "The Kaiser Team", "DRE #01234567"]
    assert call_to_action(AGENT, TEAM) == "Call or text me at (619) 555-0100, or email pat@example.test."
    assert call_to_action(solo, TEAM) == "Email me at p@example.test."
    assert call_to_action(None, TEAM) == "Reach out to The Kaiser Team to get started."


def test_dre_formats():
    assert dre_text("01234567") == dre_text("DRE #01234567") == dre_text("dre 01234567") == "DRE #01234567"
    assert dre_text("") == "" and dre_text("DRE") == ""


@pytest.mark.parametrize("agent", [
    None,
    TeamMember(name="Pat", email="p@example.test", role="agent", dre_license=""),
    TeamMember(name="Pat", email="p@example.test", role="agent", dre_license="DRE #"),
])
def test_missing_agent_name_or_dre_blocks_the_draft(agent):
    r = rendered("general", "mail", agent=agent)
    assert r.blocked_reason == BLOCKED_AGENT == "missing agent name or DRE license"
    assert r.text


def test_missing_office_address_blocks_email_only():
    team = TeamProfile(display_name="The Kaiser Team", brokerage="B", office_address="")
    assert rendered("general", "email", team=team).blocked_reason == BLOCKED_OFFICE == "missing office address"
    assert rendered("general", "mail", team=team).blocked_reason is None
    assert rendered("general", "call_task", team=team).blocked_reason is None
    both = rendered("general", "email", agent=None, team=team)
    assert both.blocked_reason == f"{BLOCKED_AGENT}; {BLOCKED_OFFICE}"
    assert blocked_reason("email", AGENT, TEAM) is None


def test_email_footer_has_office_address_and_opt_out():
    text = rendered("general", "email").text
    assert text.split("\n\n--\n")[1] == f"{TEAM.office_address}\n{EMAIL_OPT_OUT}"


def test_no_unfilled_placeholders_remain_even_with_an_empty_profile():
    bare = TeamProfile(display_name="Team")
    for recipe in RECIPES + [GENERAL]:
        for ch in CHANNELS:
            assert not re.search(r"[{}]", rendered(recipe, ch, agent=None, team=bare).text)


def test_unknown_placeholder_fails_loudly(tmp_path):
    d = tmp_path / "general"
    d.mkdir()
    (d / "letter.md").write_text("---\nfacts: []\n---\nHello {nope}.\n")
    t = load_template("general", "mail", root=tmp_path)
    with pytest.raises(KeyError):
        render("mail", t, "Dear A,", "La Jolla", "1 Main", AGENT, TEAM)


def test_renderer_is_deterministic():
    assert rendered("builder_bait", "mail").text == rendered("builder_bait", "mail").text
