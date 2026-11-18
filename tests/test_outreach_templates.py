"""Template rules (D10, D11): word counts, banned phrasing, sign-off, footer, blocked reasons."""
import re

import pytest

from territory.config import TeamMember, TeamProfile, load_client
from territory.outreach_render import (
    BLOCKED_AGENT, BLOCKED_OFFICE, CALL_REMINDER, CALL_WORDS_MAX, CHANNEL_FILE, EMAIL_OPT_OUT, EMAIL_WORDS,
    GENERAL, LETTER_WORDS, TEMPLATES_DIR, all_template_files, blocked_reason, counted_text, dre_text, load_template,
    render, signoff_lines, word_count,
)
from territory.scoring_engine import load_scoring_config

CLIENT = load_client("kaiser-team")
RECIPES = [r for r in CLIENT.enabled_recipes() if load_scoring_config()["recipes"][r].get("active") is not False]
CHANNELS = list(CHANNEL_FILE)
AGENT = TeamMember(name="Pat Test-Agent", email="pat@example.test", role="agent",
                   dre_license="DRE #01234567", phone="(619) 555-0100")
TEAM = TeamProfile(display_name="The Kaiser Team", brokerage="Example Brokerage Group",
                   office_address="1 Test Way, San Diego, CA 92037")
LONG_SALUTATION = "To the Trustee of the John, Mary and James Smith Revocable Family Trust,"   # longest we produce

BANNED = [
    r"\bneighbors?\b", r"public records?", r"records show", r"our records", r"we (know|noticed|saw|found)",
    r"according to", r"\bdeath\b", r"\bdied\b", r"\bdeceased\b", r"passed away", r"inherit", r"probate",
    r"\bestate of\b", r"tax[- ]default", r"delinquen", r"\bdebt", r"foreclos", r"non-?renewal", r"insurance",
    r"\blien", r"\bmortgage", r"distress", r"\bdefault", r"\bbankrupt", r"\bpower[- ]to[- ]sell",
]
TEAM_CLAIMS = [r"\byears? in (the )?business\b", r"\btop[- ]producer", r"#\s?1\b", r"number one", r"\branked\b",
               r"\baward", r"\bsold \d", r"\d+ homes", r"\bvolume\b", r"\bsales record", r"\bexperience[d]? with \d"]


def tpl(recipe, channel):
    return load_template(recipe, channel)


def rendered(recipe, channel, salutation="Dear John Smith,", agent=AGENT, team=TEAM):
    return render(channel, tpl(recipe, channel), salutation, "La Jolla", "2307 Calle De La Garza", agent, team)


def test_every_enabled_recipe_and_the_general_fallback_has_all_three_channels():
    for recipe in RECIPES + [GENERAL]:
        for fname in CHANNEL_FILE.values():
            assert (TEMPLATES_DIR / recipe / f"{fname}.md").exists(), f"missing {recipe}/{fname}.md"
    assert "quiet_inheritance" not in RECIPES                           # disabled: no template needed
    assert len(all_template_files()) == (len(RECIPES) + 1) * 3


def test_a_recipe_without_templates_falls_back_to_general():
    assert load_template("quiet_inheritance", "mail").key == "general/letter"
    assert load_template("builder_bait", "mail").key == "builder_bait/letter"


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
def test_letter_120_to_180_words(recipe):
    lo, hi = LETTER_WORDS
    full = rendered(recipe, "mail", LONG_SALUTATION)                    # complete sign-off, longest greeting
    assert lo <= word_count(full.text) <= hi, word_count(full.text)
    bare = rendered(recipe, "mail", "To the property owner,", agent=None, team=TeamProfile(display_name="Team"))
    assert word_count(full.body) >= lo and word_count(bare.body) >= lo    # the body alone meets the minimum


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
def test_email_80_to_130_words_with_a_subject(recipe):
    lo, hi = EMAIL_WORDS
    r = rendered(recipe, "email", LONG_SALUTATION)
    assert r.subject and r.text.startswith(f"Subject: {r.subject}\n")
    assert lo <= word_count(counted_text("email", r)) <= hi, word_count(counted_text("email", r))
    assert word_count(r.body) >= lo - 10 and word_count(r.subject) <= 12


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
def test_call_script_under_120_words_with_permission_opener_and_reminder(recipe):
    r = rendered(recipe, "call_task")
    assert word_count(r.text) < CALL_WORDS_MAX
    assert r.text.rstrip().endswith(CALL_REMINDER)
    assert CALL_REMINDER == "Manual dial only. Check Do Not Call status before calling."
    first = r.text.split("\n\n")[0]
    assert re.search(r"(okay|good) time|quick question", first, re.I) and first.strip().endswith("?")
    assert "Pat Test-Agent" in first and "DRE #01234567" in first and "The Kaiser Team" in first


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
@pytest.mark.parametrize("channel", CHANNELS)
def test_banned_phrasing_never_appears(recipe, channel):
    r = rendered(recipe, channel)
    text = (r.text + " " + (r.subject or "")).lower()
    for pat in BANNED:
        assert not re.search(pat, text), f"{recipe}/{channel}: banned phrasing {pat!r}"
    for pat in TEAM_CLAIMS:
        assert not re.search(pat, text), f"{recipe}/{channel}: unsupported claim {pat!r}"
    assert not re.search(r"\bneighbors?\b", (TEMPLATES_DIR / recipe / f"{CHANNEL_FILE[channel]}.md").read_text().lower())


@pytest.mark.parametrize("recipe", RECIPES + [GENERAL])
@pytest.mark.parametrize("channel", ["mail", "email"])
def test_opens_with_local_focus_and_a_reason(recipe, channel):
    body = rendered(recipe, channel).body
    first = body.split(".")[0]
    assert first.startswith("I work with homeowners in La Jolla") and re.search(r"\bbecause\b", first)


def test_builder_bait_and_str_exit_use_the_allowed_angles_only():
    assert "your lot may have more value under current zoning rules (estimated)" in rendered("builder_bait", "mail").body
    assert "your lot may have more value under current zoning rules (estimated)" in rendered("builder_bait", "email").body
    assert "changes in local short-term rental rules" in rendered("str_exit", "mail").body
    for recipe in RECIPES + [GENERAL]:                                   # the zoning angle belongs to builder bait only
        if recipe != "builder_bait":
            assert "zoning" not in rendered(recipe, "mail").body.lower()
        if recipe != "str_exit":
            assert "short-term rental" not in rendered(recipe, "mail").body.lower()


def test_facts_listed_by_templates_are_only_the_ones_the_text_needs():
    assert tpl("builder_bait", "mail").facts == ("sb9_lot_split_estimate", "sb79_transit_estimate")
    assert tpl("str_exit", "mail").facts == ("stro_license_removed",)
    for recipe in RECIPES + [GENERAL]:
        if recipe not in ("builder_bait", "str_exit"):
            assert all(tpl(recipe, ch).facts == () for ch in CHANNELS)


# ---- sign-off, footer, blocked reasons -----------------------------------------------------------
def test_letter_signoff_has_agent_name_dre_phone_team_and_brokerage():
    text = rendered("general", "mail").text
    assert text.endswith("Sincerely,\nPat Test-Agent\nDRE #01234567\n(619) 555-0100\nThe Kaiser Team\nExample Brokerage Group")
    assert text.startswith("Dear John Smith,\n\n")
    assert rendered("general", "mail").blocked_reason is None


def test_empty_profile_lines_are_omitted():
    team = TeamProfile(display_name="The Kaiser Team")                  # no brokerage, no office address
    agent = TeamMember(name="Pat Test-Agent", email="p@example.test", role="agent", dre_license="01234567")
    lines = signoff_lines(agent, team)
    assert lines == ["Pat Test-Agent", "DRE #01234567", "The Kaiser Team"]
    assert "\n\n" not in "\n".join(lines)


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
    assert r.text                                                          # the draft is still created


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
    footer = text.split("\n\n--\n")[1]
    assert footer == f"{TEAM.office_address}\n{EMAIL_OPT_OUT}"
    assert re.search(r"unsubscribe", footer)


def test_no_unfilled_placeholders_remain():
    for recipe in RECIPES + [GENERAL]:
        for ch in CHANNELS:
            assert not re.search(r"[{}]", rendered(recipe, ch).text)


def test_unknown_placeholder_fails_loudly(tmp_path):
    d = tmp_path / "general"
    d.mkdir()
    (d / "letter.md").write_text("---\nfacts: []\n---\nHello {nope}.\n")
    t = load_template("general", "mail", root=tmp_path)
    with pytest.raises(KeyError):
        render("mail", t, "Dear A,", "La Jolla", "1 Main", AGENT, TEAM)


def test_renderer_is_deterministic():
    assert rendered("builder_bait", "mail").text == rendered("builder_bait", "mail").text
